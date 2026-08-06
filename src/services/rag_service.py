import os
from enum import StrEnum
import logging
from typing import Any

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from src.llm import create_chat_model
from src.logging_config import setup_logging

setup_logging()

logger = logging.getLogger(__name__)


class Channel(StrEnum):
    CHAT = "chat"
    VOICE = "voice"


def _append_image_evidence(
    context_docs: list[Document],
    max_images_per_article: int = 3,
    max_total_images: int = 6,
) -> list[Document]:
    """Enrich RAG context with image caption + visual summary text.

    For each retrieved article, fetches associated image captions from SQLite
    (primary + linked cases via BFS co-retrieval, handled inside
    get_case_images) and appends them as extra Document entries. The stuff
    chain concatenates these into the LLM prompt, so answers can reference
    what screenshots/diagrams actually show — grounded in caption text, not
    invented UI details.
    """
    if not context_docs:
        return context_docs

    try:
        from src.services.image_retrieval import get_case_images, filter_images_safe
    except Exception as exc:
        logger.debug("[RAG IMAGES] image_retrieval import failed: %s", exc)
        return context_docs

    seen_article_ids: list[str] = []
    for doc in context_docs:
        aid = doc.metadata.get("article_id") if isinstance(doc.metadata, dict) else None
        if aid and aid not in seen_article_ids:
            seen_article_ids.append(aid)

    if not seen_article_ids:
        return context_docs

    evidence_docs: list[Document] = []
    total = 0
    for aid in seen_article_ids:
        if total >= max_total_images:
            break
        try:
            images = get_case_images(aid, include_linked=True, limit=max_images_per_article)
            # Apply image safety rules
            article_meta = {}
            for doc in context_docs:
                if doc.metadata.get("article_id") == aid:
                    article_meta = doc.metadata
                    break
            images = filter_images_safe(images, article_id=aid, article_meta=article_meta)
        except Exception as exc:
            logger.debug("[RAG IMAGES] get_case_images failed for %s: %s", aid, exc)
            continue
        if not images:
            continue

        for img in images:
            if total >= max_total_images:
                break
            caption = (img.get("caption") or "").strip()
            visual = (img.get("visual_summary") or "").strip()
            if not caption and not visual:
                continue
            source_tag = aid if img.get("is_primary") else f"{aid} (linked → {img.get('linked_from', aid)})"
            block_lines = [f"IMAGE EVIDENCE [{source_tag}] page {img.get('page_number', '?')}"]
            if caption:
                block_lines.append(f"caption: {caption}")
            if visual:
                block_lines.append(f"visual: {visual}")
            evidence_docs.append(
                Document(
                    page_content="\n".join(block_lines),
                    metadata={
                        "article_id": aid,
                        "doc_type": "image_evidence",
                        "image_id": img.get("image_id"),
                    },
                )
            )
            total += 1

    if evidence_docs:
        logger.info("[RAG IMAGES] Appended %d image evidence blocks", len(evidence_docs))
    return list(context_docs) + evidence_docs


def to_qdrant_filter(metadata_filter: dict | qmodels.Filter | None) -> qmodels.Filter | None:
    """Convert dict-style metadata filters to Qdrant Filter objects."""
    if metadata_filter is None:
        return None
    if isinstance(metadata_filter, qmodels.Filter):
        return metadata_filter

    conditions: list[qmodels.FieldCondition] = []

    def _eq(key: str, value: Any) -> None:
        if isinstance(value, dict) and "$eq" in value:
            value = value["$eq"]
        conditions.append(
            qmodels.FieldCondition(
                key=f"metadata.{key}",
                match=qmodels.MatchValue(value=value),
            )
        )

    if "$and" in metadata_filter:
        for item in metadata_filter["$and"]:
            if not isinstance(item, dict):
                continue
            for key, value in item.items():
                _eq(key, value)
    else:
        for key, value in metadata_filter.items():
            if key.startswith("$"):
                continue
            _eq(key, value)

    return qmodels.Filter(must=conditions) if conditions else None


# ── FlashRank Reranker ────────────────────────────────────────────────────────

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        from flashrank import Ranker
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "flashrank_cache")
        cache_dir = os.path.normpath(cache_dir)
        _reranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir=cache_dir)
    return _reranker


def _rerank_documents(query: str, documents: list[Document], top_k: int = 6) -> list[Document]:
    """Rerank retrieved documents using FlashRank for precision."""
    if not documents:
        return documents
    from flashrank import RerankRequest
    passages = [
        {"id": i, "text": doc.page_content, "meta": doc.metadata}
        for i, doc in enumerate(documents)
    ]
    rerank_request = RerankRequest(query=query, passages=passages)
    ranker = _get_reranker()
    results = ranker.rerank(rerank_request)
    reranked_ids = [int(r["id"]) for r in results[:top_k]]
    return [documents[i] for i in reranked_ids]


# ── RAGService ────────────────────────────────────────────────────────────────

class RAGService:
    """Runtime RAG over a pre-built local Qdrant index (see data_injection)."""

    def __init__(
        self,
        kb_dir: str = "KB",
        qdrant_path: str | None = None,
        collection: str | None = None,
    ):
        logger.info("RAG service initialise (Qdrant connect-only)")
        from src.config import (
            OPENAI_EMBEDDING_MODEL,
            QDRANT_COLLECTION,
            QDRANT_PATH,
            SECTION0_CACHE_PATH,
        )

        self.kb_dir = kb_dir
        self.qdrant_path = os.path.abspath(qdrant_path or QDRANT_PATH)
        self.collection = collection or QDRANT_COLLECTION
        self.section0_cache_path = SECTION0_CACHE_PATH
        self.section0_prompt: str = ""
        self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)
        self.vectorstore = None

        if not os.path.exists(self.qdrant_path) or not os.listdir(self.qdrant_path):
            logger.error(
                "Local Qdrant not found at %s. Run: uv run python -m data_injection",
                self.qdrant_path,
            )
            return

        try:
            from src.services.qdrant_client_factory import get_qdrant_client, check_qdrant_health

            client = get_qdrant_client(self.qdrant_path)
            if not check_qdrant_health(client, self.collection):
                client.close()
                return

            self.vectorstore = QdrantVectorStore(
                client=client,
                collection_name=self.collection,
                embedding=self.embeddings,
            )
        except Exception as exc:
            logger.error("Failed to open local Qdrant: %s", exc)
            self.vectorstore = None
            return

        self._load_section0_prompt()

        self.llm = create_chat_model(temperature=0)

        self.chat_prompt = ChatPromptTemplate.from_messages([
            ("system", self._build_system_prompt()),
            ("human", "{input}"),
        ])
        self.voice_prompt = ChatPromptTemplate.from_messages([
            ("system", self._build_voice_system_prompt()),
            ("human", "{input}"),
        ])

        self.chat_chain = create_stuff_documents_chain(self.llm, self.chat_prompt)
        self.voice_chain = create_stuff_documents_chain(self.llm, self.voice_prompt)

    def _load_section0_prompt(self):
        """Load Section 0 from injection cache, with KB DOCX fallback."""
        if self.section0_prompt:
            return

        if os.path.exists(self.section0_cache_path):
            with open(self.section0_cache_path, encoding="utf-8") as f:
                self.section0_prompt = f.read().strip()
            if self.section0_prompt:
                return

        # Fallback: read from v2.2 DOCX if cache missing
        from data_injection.kb_parser import is_v22_file
        if not os.path.exists(self.kb_dir):
            return
        for filename in os.listdir(self.kb_dir):
            if filename.endswith(".docx") and is_v22_file(filename):
                import docx2txt
                text = docx2txt.process(os.path.join(self.kb_dir, filename))
                first_article = text.find("ARTICLE START:")
                if first_article > 0:
                    self.section0_prompt = text[:first_article].strip()
                break

    def _build_retriever(self, metadata_filter: dict | None = None):
        """Build a retriever with optional metadata filter."""
        search_kwargs: dict = {"k": 12}
        qfilter = to_qdrant_filter(metadata_filter)
        if qfilter is not None:
            search_kwargs["filter"] = qfilter

        return self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs=search_kwargs,
        )

    def query(
        self,
        input_text: str,
        channel: str = None,
        metadata_filter: dict | None = None,
        intent: str = "",
        device_type: str = "",
    ) -> dict:
        """
        Query the RAG pipeline (Hybrid by default) with recursive co-retrieval.

        Pipeline (hybrid):
          1. MMR vector retrieval + device filter + rerank
          2. Recursive SQLite co-retrieval (BFS, max depth)
          3. Ordered context (primary → companions)
          4. LLM generation
        """
        logger.info(f"[RAG SERVICE] Using channel: {channel}")
        logger.info(f"[RAG SERVICE] Input: {input_text}")

        if not self.vectorstore:
            from src.config import RAG_RETRIEVAL_METHOD
            if RAG_RETRIEVAL_METHOD == "vectorless":
                return self._invoke_vectorless(input_text, channel, intent, device_type)
            return {
                "answer": (
                    "Error: RAG not initialized. Local Qdrant index missing. "
                    "Run: uv run python -m data_injection"
                ),
                "context": [],
            }

        result = self._invoke_rag(
            input_text, channel, metadata_filter, intent=intent, device_type=device_type
        )

        if metadata_filter and not result.get("context"):
            result = self._invoke_rag(
                input_text, channel, metadata_filter=None, intent=intent, device_type=device_type
            )

        return result

    def _invoke_vectorless(
        self,
        input_text: str,
        channel: str | None,
        intent: str,
        device_type: str,
    ) -> dict:
        from src.services.vectorless_rag import vectorless_retrieve

        final_context, co_meta = vectorless_retrieve(
            query=input_text,
            intent=intent,
            device_type=device_type,
        )
        qa_chain = self.voice_chain if channel == Channel.VOICE else self.chat_chain
        final_context = _append_image_evidence(final_context)
        answer = qa_chain.invoke({"input": input_text, "context": final_context})
        return {"answer": answer, "context": final_context, "co_retrieval_meta": co_meta}

    def _invoke_rag(
        self,
        input_text: str,
        channel: str = None,
        metadata_filter: dict | None = None,
        intent: str = "",
        device_type: str = "",
    ) -> dict:
        """Run retrieval + recursive co-retrieval + ordered context + generation."""
        import time
        from src.config import RAG_RETRIEVAL_METHOD

        start_time = time.time()
        co_meta: dict = {}

        if RAG_RETRIEVAL_METHOD == "hybrid":
            from src.services.hybrid_rag import hybrid_retrieve

            try:
                final_context, co_meta = hybrid_retrieve(
                    query=input_text,
                    vectorstore=self.vectorstore,
                    intent=intent,
                    device_type=device_type,
                    top_k=6,
                    rerank_fn=_rerank_documents,
                )
            except Exception as exc:
                logger.warning("[RAG SERVICE] Hybrid failed, falling back to vector: %s", exc)
                final_context = self._vector_retrieve_context(
                    input_text, metadata_filter
                )
        elif RAG_RETRIEVAL_METHOD == "vectorless":
            from src.services.vectorless_rag import vectorless_retrieve

            final_context, co_meta = vectorless_retrieve(
                query=input_text,
                intent=intent,
                device_type=device_type,
            )
        else:
            final_context = self._vector_retrieve_context(input_text, metadata_filter)

        latency_ms = (time.time() - start_time) * 1000
        article_ids = [
            d.metadata.get("article_id", "") for d in final_context if d.metadata.get("article_id")
        ]
        method = co_meta.get("method", RAG_RETRIEVAL_METHOD)
        logger.info(
            "[RAG SERVICE] %s retrieval: %d docs in %.1fms | articles: %s",
            method,
            len(final_context),
            latency_ms,
            article_ids[:8],
        )
        try:
            from src.services.kb_database import log_retrieval
            log_retrieval(
                query=input_text,
                method=method,
                intent=intent,
                device_type=device_type,
                articles_returned=article_ids,
                latency_ms=latency_ms,
                co_retrieval_applied=co_meta.get("co_retrieval_applied", False),
            )
        except Exception:
            pass

        qa_chain = self.voice_chain if channel == Channel.VOICE else self.chat_chain
        final_context = _append_image_evidence(final_context)
        answer = qa_chain.invoke({"input": input_text, "context": final_context})

        return {
            "answer": answer,
            "context": final_context,
            "co_retrieval_meta": co_meta,
        }

    def _vector_retrieve_context(
        self,
        input_text: str,
        metadata_filter: dict | None,
    ) -> list[Document]:
        """Legacy vector path with recursive co-retrieval and ordered context."""
        from src.services.co_retrieval import expand_co_retrieval
        from src.services.article_context import build_ordered_context
        from src.config import CO_RETRIEVAL_MAX_DEPTH

        retriever = self._build_retriever(metadata_filter)
        raw_docs = retriever.invoke(input_text)
        primary_docs = _rerank_documents(input_text, raw_docs, top_k=6)

        seed_ids = [
            d.metadata.get("article_id", "")
            for d in primary_docs
            if d.metadata.get("article_id")
        ]
        co_result = expand_co_retrieval(
            seed_ids, max_depth=CO_RETRIEVAL_MAX_DEPTH, exclude_ids=set(seed_ids)
        )
        return build_ordered_context(
            primary_docs=primary_docs,
            companion_ids=co_result.companion_ids,
            retrieval_method="vector",
        )

    def _build_system_prompt(self) -> str:
        """Build the RAG system prompt incorporating v2.2 Section 0 rules."""
        base_rules = (
            "You are an expert Technical Support AI Agent for the Setomatic/SpyderWash ecosystem. "
            "Setomatic Systems is the company that manufactures SpyderWash — treat any SpyderWash "
            "context as relevant when answering questions about Setomatic, and vice versa.\n\n"
        )

        if self.section0_prompt:
            section0_condensed = self._condense_section0(self.section0_prompt)
            base_rules += f"KNOWLEDGE BASE RULES (from SpyderWash AI Support KB):\n{section0_condensed}\n\n"

        base_rules += (
            "RESPONSE RULES:\n"
            "- Use ONLY the provided context to answer. Do NOT invent product behavior, settings, "
            "fees, timelines, account status, or troubleshooting results.\n"
            "- If the answer is not in the context, explicitly state that and direct the Operator "
            "to SpyderWash Support.\n"
            "- Start with a direct answer in the first 1-2 sentences.\n"
            "- For reported malfunctions: provide recommended steps ordered easiest to most complex.\n"
            "- For informational questions: provide instructions without requiring diagnostic tests.\n"
            "- ALWAYS provide complete, step-by-step instructions for each new question, even if "
            "similar steps were given earlier in the conversation. Treat each question independently.\n"
            "- Do NOT request evidence (screenshots, IDs, logs) until troubleshooting steps have failed.\n"
            "- Even if the Operator's malfunction report is brief or general (e.g. \"X is failing\", "
            "\"X is not working\"), NEVER respond with only a clarifying question. Always give the "
            "best-matching recommended steps from context first; you may add one optional clarifying "
            "question at the end if it would narrow the fix, but the steps must come first.\n"
            "- If the Operator asks what specific type/model/variant of hardware (e.g. Control Board, "
            "Card Reader) is installed on their machine, and the context explains how to identify or "
            "distinguish between types, answer with that identification guidance (e.g. how to tell "
            "Relay vs Serial apart, where to find labels/Bluetooth ID) instead of refusing because you "
            "cannot see their physical unit.\n"
            "- Never quote fees, contract terms, or account-specific details without verification.\n"
            "- Never create, authorize, or claim to have opened an RMA, warranty claim, or return.\n"
            "- NEVER show internal article IDs (KB-XXX-XXX) to the operator. When companion articles "
            "are provided in context, integrate their steps seamlessly into one unified answer. "
            "The operator should receive a single coherent response, not references to case numbers.\n"
            "- When context includes PRIMARY PROCEDURE and CONTINUE WITH RELATED PROCEDURE blocks, "
            "follow the primary recommended steps first in order, then continue with related "
            "companion steps in the order provided. Do not renumber steps randomly or mix "
            "device-specific procedures across POS, Kiosk, Hub, and Card Reader.\n"
            "- When images are provided alongside case text, reference them naturally in your response "
            "(e.g. 'as shown in the screenshot'). Follow linked-case order for images too — "
            "primary case visuals first, then companion case visuals.\n"
            "- Do NOT describe UI elements, buttons, or labels that are not mentioned in the image "
            "caption or visual summary. Only reference what the image evidence confirms.\n"
            "- NEVER end your response with 'Did this resolve the issue?', 'Did this resolve the issue? (Yes/No)', "
            "or any similar follow-up resolution question. Just provide the steps and end.\n"
            "\n\nContext:\n{context}"
        )
        return base_rules

    def _build_voice_system_prompt(self) -> str:
        """Build the RAG system prompt for voice channel."""
        base_rules = (
            "You are an expert Technical Support AI Agent for the "
            "Setomatic/SpyderWash ecosystem speaking with an operator over a live phone call.\n\n"
        )

        if self.section0_prompt:
            section0_condensed = self._condense_section0(self.section0_prompt)
            base_rules += f"KNOWLEDGE BASE RULES (from SpyderWash AI Support KB):\n{section0_condensed}\n\n"

        base_rules += (
            "RESPONSE RULES:\n"
            "Your goal is to help the caller troubleshoot machine issues in a natural, friendly, "
            "and professional conversational manner. "

            "Use ONLY the provided context to answer the operator's questions. "
            "Do not invent information or make assumptions beyond the provided context. "

            "Speak as if you are talking to a real person over the phone. "
            "Use short, natural sentences that are easy to understand when spoken aloud. "
            "Avoid long paragraphs, markdown, bullet points, numbered lists, tables, special "
            "characters, code formatting, or technical document language. "

            "Explain troubleshooting instructions one step at a time. "
            "After giving a step, allow the caller to respond before continuing unless the caller "
            "specifically asks for all of the remaining steps. "

            "Do not overwhelm the caller with excessive information in one response. "
            "Keep each response concise while still being complete enough to move the troubleshooting "
            "forward. "

            "If additional information is required before determining the correct solution, "
            "ask one clear follow-up question instead of guessing. "

            "If the caller's request is unclear, incomplete, or appears to have been interrupted, "
            "politely ask the caller to repeat or clarify instead of making assumptions. "
            "For example, say 'I'm sorry, I didn't quite catch that. Could you please repeat it?' "

            "Never mention documents, manuals, PDFs, release notes, retrieval systems, vector "
            "databases, the knowledge base, search results, context, or where your information came from. "
            "Present all information naturally as if you already know it. "

            "If the answer cannot be found in the provided context, politely explain that you "
            "don't have enough information to answer confidently and ask for any additional "
            "details that may help. Do not fabricate an answer. "

            "If the caller says 'thank you', 'thanks', 'bye', 'goodbye', 'that's all', "
            "'I don't need anything else', or otherwise clearly indicates that the conversation "
            "has ended, politely thank them, wish them a good day, and naturally conclude the conversation. "

            "If the caller interrupts while you are speaking, stop your current explanation and "
            "focus only on answering the caller's latest request. Do not continue the previous "
            "response unless the caller asks you to. "

            "If the caller changes topics, immediately switch to the new topic without referring "
            "back to the previous answer. "

            "Maintain a calm, patient, professional, and empathetic tone throughout the call. "
            "\n\nContext:\n{context}"
        )
        return base_rules

    def _condense_section0(self, section0: str) -> str:
        """Filter Section 0 to keep only operational response rules."""
        from src.services.kb_ingest import clean_section0
        return clean_section0(section0)

