import os
import re
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from src.llm import create_chat_model

# ── v2.2 Article Parser ──────────────────────────────────────────────────────

_ARTICLE_PATTERN = re.compile(
    r"ARTICLE START:\s*(KB-[A-Z]+-\d+)\s*(.*?)ARTICLE END:\s*\1",
    re.DOTALL,
)

_METADATA_PATTERN = re.compile(
    r"METADATA:\s*category=([^;]+);\s*product=([^;]+);\s*audience=([^;]+);\s*intent=([^;]+);\s*search_terms=(.+)",
    re.IGNORECASE,
)

_CO_RETRIEVAL_PATTERN = re.compile(
    r"CO-RETRIEVAL RULE:?\s*(.+?)(?:\n|$)", re.IGNORECASE
)

_ARTICLE_ID_REF_PATTERN = re.compile(r"KB-[A-Z]+-\d+")

_V22_FILENAME_MARKERS = ("ai_support_knowledge_base", "ai support knowledge base")
_BIBLE_FILENAME_MARKERS = ("bible",)

_BIBLE_TROUBLESHOOT_START_MARKER = "Troubleshooting\n\nNetwork Issues"
_BIBLE_INSTALL_START_MARKERS = [
    "Alliance (Speed Queen",
    "Speed Queen Touch/Midas",
    "ADC\n",
    "American (Whirlpool",
    "Continental\n",
    "Dexter\n",
    "Greenwald\n",
    "Maytag\n",
    "Primus\n",
]


def _is_v22_file(filename: str) -> bool:
    name_lower = filename.lower().replace("-", "_").replace(" ", "_")
    return any(marker in name_lower for marker in _V22_FILENAME_MARKERS)


def _is_bible_file(filename: str) -> bool:
    name_lower = filename.lower()
    return any(marker in name_lower for marker in _BIBLE_FILENAME_MARKERS)


def _parse_v22_articles(text: str) -> tuple[list[Document], str, list[Document]]:
    """
    Parse v2.2 into:
      1. List of Documents (one per article with structured metadata)
      2. Section 0 text (AI Retrieval and Response Rules) for system prompt
      3. Visual reference chunks (post-article content)
    """
    first_article_idx = text.find("ARTICLE START:")
    if first_article_idx < 0:
        return [], "", []

    section0_text = text[:first_article_idx].strip()

    articles: list[Document] = []
    for match in _ARTICLE_PATTERN.finditer(text):
        article_id = match.group(1)
        body = match.group(2).strip()

        metadata = {
            "article_id": article_id,
            "source_file": "SpyderWash_AI_Support_Knowledge_Base (v2.2).docx",
            "doc_type": "kb_article",
            "brand": "SpyderWash",
            "source_priority": "primary",
            "category": "",
            "product": "",
            "intent": "",
            "search_terms": "",
            "status": "current",
            "co_retrieval_ids": "",
        }

        meta_match = _METADATA_PATTERN.search(body)
        if meta_match:
            metadata["category"] = meta_match.group(1).strip()
            metadata["product"] = meta_match.group(2).strip()
            metadata["intent"] = meta_match.group(4).strip()
            metadata["search_terms"] = meta_match.group(5).strip()

        if "CURRENT" in body[:200].upper():
            metadata["status"] = "current"
        elif "DEPRECATED" in body[:200].upper() or "SUPERSEDED" in body[:200].upper():
            metadata["status"] = "deprecated"

        co_ret_match = _CO_RETRIEVAL_PATTERN.search(body)
        if co_ret_match:
            co_ids = _ARTICLE_ID_REF_PATTERN.findall(co_ret_match.group(1))
            co_ids = [cid for cid in co_ids if cid != article_id]
            metadata["co_retrieval_ids"] = ";".join(co_ids) if co_ids else ""

        content = f"[{article_id}] {body}"
        articles.append(Document(page_content=content, metadata=metadata))

    last_article_end = text.rfind("ARTICLE END:")
    if last_article_end > 0:
        end_line = text.find("\n", last_article_end)
        visual_text = text[end_line:].strip() if end_line > 0 else ""
    else:
        visual_text = ""

    visual_chunks: list[Document] = []
    if visual_text and len(visual_text) > 200:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200, chunk_overlap=100,
            separators=["\nFigure ", "\n\n", "\n"],
        )
        for chunk in splitter.split_text(visual_text):
            visual_chunks.append(Document(
                page_content=f"[VISUAL REFERENCE]\n{chunk}",
                metadata={
                    "source_file": "SpyderWash_AI_Support_Knowledge_Base (v2.2).docx",
                    "doc_type": "visual_reference",
                    "brand": "SpyderWash",
                    "source_priority": "secondary",
                    "article_id": "",
                    "category": "visual_reference",
                    "product": "",
                    "intent": "",
                    "search_terms": "",
                    "status": "current",
                    "co_retrieval_ids": "",
                },
            ))

    return articles, section0_text, visual_chunks


_BIBLE_OPERATOR_START_MARKER = "Operator Portal"
# Include Installation FAQ + Highest-Frequency Questions (Control Board type,
# Relay vs Serial, hubs, Bluetooth ID). Stop before Voiceover / PCI / wiring.
_BIBLE_OPERATOR_END_MARKER = "Voiceover: SpyderWash Troubleshooting Guide"


def _parse_bible_selective(text: str) -> list[Document]:
    """
    Ingest troubleshooting sections (1-14) AND operator-relevant reference
    sections (Portal, POS, Kiosk, Hub, Mobile App, Installation FAQ, etc.).
    Still excludes brand-specific wiring diagrams and internal PCI notes.
    """
    troubleshoot_start = text.find(_BIBLE_TROUBLESHOOT_START_MARKER)
    if troubleshoot_start < 0:
        troubleshoot_start = text.find("Troubleshooting")
    if troubleshoot_start < 0:
        return []

    install_start = len(text)
    for marker in _BIBLE_INSTALL_START_MARKERS:
        idx = text.find(marker, troubleshoot_start + 100)
        if 0 < idx < install_start:
            install_start = idx

    troubleshoot_content = text[troubleshoot_start:install_start].strip()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\nSection ", "\n\n", "\n", ". "],
    )

    chunks: list[Document] = []

    if troubleshoot_content:
        for chunk_text in splitter.split_text(troubleshoot_content):
            chunks.append(Document(
                page_content=f"[BIBLE SUPPLEMENT]\n{chunk_text}",
                metadata={
                    "source_file": "Setomatic Bible.docx",
                    "doc_type": "bible_supplement",
                    "brand": "SpyderWash",
                    "source_priority": "secondary",
                    "article_id": "",
                    "category": "troubleshooting",
                    "product": "Network / Power / Connectivity",
                    "intent": "",
                    "search_terms": "",
                    "status": "current",
                    "co_retrieval_ids": "",
                },
            ))

    op_start = text.find(_BIBLE_OPERATOR_START_MARKER)
    op_end = text.find(_BIBLE_OPERATOR_END_MARKER)
    if op_end < 0:
        op_end = len(text)

    if op_start > 0 and op_start > install_start and op_start < op_end:
        operator_content = text[op_start:op_end].strip()
        if operator_content and len(operator_content) >= 100:
            for chunk_text in splitter.split_text(operator_content):
                chunks.append(Document(
                    page_content=f"[BIBLE - Operator Reference]\n{chunk_text}",
                    metadata={
                        "source_file": "Setomatic Bible.docx",
                        "doc_type": "bible_operator",
                        "brand": "SpyderWash",
                        "source_priority": "secondary",
                        "article_id": "",
                        "category": "Operator Reference",
                        "product": "SpyderWash Operator Portal / POS / Kiosk / Hub",
                        "intent": "",
                        "search_terms": "",
                        "status": "current",
                        "co_retrieval_ids": "",
                    },
                ))

    return chunks


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
    def __init__(self, kb_dir: str = "KB", persist_dir: str = "./chroma_db", force_reingest: bool = False):
        self.kb_dir = kb_dir
        self.persist_dir = persist_dir
        self.section0_prompt: str = ""
        from src.config import OPENAI_EMBEDDING_MODEL
        self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)

        db_exists = os.path.exists(self.persist_dir) and len(os.listdir(self.persist_dir)) > 0
        if db_exists and not force_reingest:
            self.vectorstore = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
            self._load_section0_prompt()
        else:
            splits = self.load_and_process_documents()
            if splits:
                self.vectorstore = self.initialize_vectorstore(splits)
            else:
                self.vectorstore = None

        if self.vectorstore:
            self.retriever = self.vectorstore.as_retriever(
                search_type="mmr",
                search_kwargs={"k": 12, "fetch_k": 40, "lambda_mult": 0.5},
            )
            self.llm = create_chat_model(temperature=0)
        else:
            self.retriever = None

    def _load_section0_prompt(self):
        """Load Section 0 from v2.2 if not already cached."""
        if self.section0_prompt:
            return
        v22_path = self._find_v22_file()
        if v22_path:
            import docx2txt
            text = docx2txt.process(v22_path)
            first_article = text.find("ARTICLE START:")
            if first_article > 0:
                self.section0_prompt = text[:first_article].strip()

    def _find_v22_file(self) -> str | None:
        if not os.path.exists(self.kb_dir):
            return None
        for filename in os.listdir(self.kb_dir):
            if filename.endswith(".docx") and _is_v22_file(filename):
                return os.path.join(self.kb_dir, filename)
        return None

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def load_and_process_documents(self) -> list[Document] | None:
        """
        Article-aware ingestion pipeline:
          - v2.2: parse 171 structured articles as atomic chunks with full metadata
          - Bible: selectively ingest only troubleshooting sections (1-14)
          - Other KB files: standard chunking (PDF/TXT fallback)
        """
        if not os.path.exists(self.kb_dir):
            return None

        all_chunks: list[Document] = []

        for filename in os.listdir(self.kb_dir):
            file_path = os.path.join(self.kb_dir, filename)
            if not os.path.isfile(file_path):
                continue

            if filename.endswith(".docx") and _is_v22_file(filename):
                all_chunks.extend(self._ingest_v22(file_path))

            elif filename.endswith(".docx") and _is_bible_file(filename):
                all_chunks.extend(self._ingest_bible(file_path))

            elif filename.endswith(".pdf"):
                all_chunks.extend(self._ingest_generic(file_path, PyPDFLoader))

            elif filename.endswith(".txt"):
                all_chunks.extend(self._ingest_generic(file_path, TextLoader, encoding="utf-8"))

            elif filename.endswith(".docx"):
                all_chunks.extend(self._ingest_generic(file_path, Docx2txtLoader))

        return all_chunks if all_chunks else None

    def _ingest_v22(self, file_path: str) -> list[Document]:
        """Parse v2.2 into article-level atomic chunks with structured metadata.
        Visual reference chunks (figure tables) are excluded — they pollute
        similarity search with keyword-dense index text."""
        import docx2txt
        text = docx2txt.process(file_path)

        articles, section0, _visual_chunks = _parse_v22_articles(text)
        self.section0_prompt = section0
        return articles

    def _ingest_bible(self, file_path: str) -> list[Document]:
        """Selectively ingest only operator-relevant troubleshooting from the Bible."""
        import docx2txt
        text = docx2txt.process(file_path)
        return _parse_bible_selective(text)

    def _ingest_generic(self, file_path: str, loader_class, **loader_kwargs) -> list[Document]:
        """Fallback: standard chunking for other KB files."""
        try:
            raw_docs = loader_class(file_path, **loader_kwargs).load()
        except Exception:
            return []

        filename = os.path.basename(file_path)
        for doc in raw_docs:
            doc.metadata["source_file"] = filename
            doc.metadata["doc_type"] = "general"
            doc.metadata["brand"] = "SpyderWash"
            doc.metadata["source_priority"] = "secondary"
            doc.metadata["article_id"] = ""
            doc.metadata["category"] = ""
            doc.metadata["product"] = ""
            doc.metadata["intent"] = ""
            doc.metadata["search_terms"] = ""
            doc.metadata["status"] = "current"
            doc.metadata["co_retrieval_ids"] = ""

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800, chunk_overlap=100,
            separators=["\n\n", "\n", ". ", " "],
        )
        splits = splitter.split_documents(raw_docs)

        for chunk in splits:
            source = chunk.metadata.get("source_file", "Unknown")
            page = chunk.metadata.get("page", "N/A")
            chunk.page_content = f"[DOCUMENT: {source} | PAGE: {page}]\n{chunk.page_content}"

        return splits

    def initialize_vectorstore(self, splits: list[Document]):
        """Build a fresh Chroma vectorstore from the enriched splits."""
        return Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def _build_retriever(self, metadata_filter: dict | None = None):
        """Build a retriever with optional metadata filter and MMR."""
        search_kwargs = {
            "k": 12,
            "fetch_k": 40,
            "lambda_mult": 0.5,
        }
        if metadata_filter:
            search_kwargs["filter"] = metadata_filter

        return self.vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs=search_kwargs,
        )

    def _fetch_co_retrieval_docs(self, documents: list[Document]) -> list[Document]:
        """
        Check retrieved documents for co-retrieval rules and fetch companion articles.
        """
        needed_ids: set[str] = set()
        retrieved_ids = {doc.metadata.get("article_id", "") for doc in documents}

        for doc in documents:
            co_ids_str = doc.metadata.get("co_retrieval_ids", "")
            if co_ids_str:
                for cid in co_ids_str.split(";"):
                    cid = cid.strip()
                    if cid and cid not in retrieved_ids:
                        needed_ids.add(cid)

        if not needed_ids:
            return []

        companion_docs: list[Document] = []
        for article_id in needed_ids:
            results = self.vectorstore.similarity_search(
                "", k=1,
                filter={"article_id": {"$eq": article_id}},
            )
            companion_docs.extend(results)

        return companion_docs

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
            "- Never quote fees, contract terms, or account-specific details without verification.\n"
            "- Never create, authorize, or claim to have opened an RMA, warranty claim, or return.\n"
            "\n\nContext:\n{context}"
        )
        return base_rules

    def _condense_section0(self, section0: str) -> str:
        """Extract key operational rules from Section 0 (skip preamble/headers)."""
        lines = section0.split("\n")
        useful_lines = []
        skip_headers = {"SPYDERWASH AI SUPPORT KNOWLEDGE BASE", "SPYDERWASH", "AI Support Knowledge Base"}
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if any(h in stripped for h in skip_headers):
                continue
            if stripped.startswith("Operator-Facing Edition") or stripped.startswith("Setomatic Systems"):
                continue
            if stripped.startswith("Primary purpose"):
                continue
            useful_lines.append(stripped)

        condensed = "\n".join(useful_lines)
        if len(condensed) > 6000:
            condensed = condensed[:6000]
        return condensed

    def query(self, input_text: str, metadata_filter: dict | None = None) -> dict:
        """
        Query the RAG pipeline with FlashRank reranking and co-retrieval.

        Pipeline:
          1. MMR retrieval (k=8, fetch_k=30)
          2. FlashRank rerank to top 4
          3. Co-retrieval: fetch mandatory companion articles
          4. LLM generation with Section 0 rules in system prompt
        """
        if not self.vectorstore:
            return {"answer": "Error: RAG Chain not initialized (no KB documents found).", "context": []}

        result = self._invoke_rag(input_text, metadata_filter)

        if metadata_filter and not result.get("context"):
            result = self._invoke_rag(input_text, metadata_filter=None)

        return result

    def _invoke_rag(self, input_text: str, metadata_filter: dict | None = None) -> dict:
        """Run retrieval + reranking + co-retrieval + generation."""
        retriever = self._build_retriever(metadata_filter)
        raw_docs = retriever.invoke(input_text)

        reranked_docs = _rerank_documents(input_text, raw_docs, top_k=6)

        companion_docs = self._fetch_co_retrieval_docs(reranked_docs)
        final_context = companion_docs + reranked_docs

        system_prompt = self._build_system_prompt()
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        qa_chain = create_stuff_documents_chain(self.llm, prompt)
        answer = qa_chain.invoke({"input": input_text, "context": final_context})

        return {"answer": answer, "context": final_context}
