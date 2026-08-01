"""Parse KB DOCX/PDF/TXT into LangChain Documents for Qdrant indexing."""
from __future__ import annotations

import os
import re

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

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

_BIBLE_OPERATOR_START_MARKER = "Operator Portal"
_BIBLE_OPERATOR_END_MARKER = "Voiceover: SpyderWash Troubleshooting Guide"


def is_v22_file(filename: str) -> bool:
    name_lower = filename.lower().replace("-", "_").replace(" ", "_")
    return any(marker in name_lower for marker in _V22_FILENAME_MARKERS)


def is_bible_file(filename: str) -> bool:
    name_lower = filename.lower()
    return any(marker in name_lower for marker in _BIBLE_FILENAME_MARKERS)


def parse_v22_articles(text: str) -> tuple[list[Document], str, list[Document]]:
    """
    Parse v2.2 into:
      1. Documents (one per article with structured metadata)
      2. Section 0 text (AI Retrieval and Response Rules)
      3. Visual reference chunks (post-article content; not indexed by default)
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


def parse_bible_selective(text: str) -> list[Document]:
    """Ingest troubleshooting + operator FAQ; exclude brand wiring / PCI / voiceover."""
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


def _ingest_v22(file_path: str) -> tuple[list[Document], str]:
    import docx2txt
    text = docx2txt.process(file_path)
    articles, section0, _visual_chunks = parse_v22_articles(text)
    return articles, section0


def _ingest_bible(file_path: str) -> list[Document]:
    import docx2txt
    text = docx2txt.process(file_path)
    return parse_bible_selective(text)


def _ingest_generic(file_path: str, loader_class, **loader_kwargs) -> list[Document]:
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


def load_and_process_documents(kb_dir: str = "KB") -> tuple[list[Document], str]:
    """
    Article-aware ingestion:
      - v2.2: atomic articles with metadata
      - Bible: selective troubleshooting + operator FAQ
      - Other KB files: standard chunking
    Returns (chunks, section0_text).
    """
    if not os.path.exists(kb_dir):
        return [], ""

    all_chunks: list[Document] = []
    section0 = ""

    for filename in os.listdir(kb_dir):
        file_path = os.path.join(kb_dir, filename)
        if not os.path.isfile(file_path):
            continue

        if filename.endswith(".docx") and is_v22_file(filename):
            articles, section0 = _ingest_v22(file_path)
            all_chunks.extend(articles)

        elif filename.endswith(".docx") and is_bible_file(filename):
            all_chunks.extend(_ingest_bible(file_path))

        elif filename.endswith(".pdf"):
            all_chunks.extend(_ingest_generic(file_path, PyPDFLoader))

        elif filename.endswith(".txt"):
            all_chunks.extend(_ingest_generic(file_path, TextLoader, encoding="utf-8"))

        elif filename.endswith(".docx"):
            all_chunks.extend(_ingest_generic(file_path, Docx2txtLoader))

    return all_chunks, section0
