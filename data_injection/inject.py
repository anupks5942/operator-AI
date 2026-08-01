"""Build local on-disk Qdrant index from KB/.

Usage:
    uv run python -m data_injection
    uv run python -m data_injection --kb-dir KB --force
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from data_injection.kb_parser import load_and_process_documents

logger = logging.getLogger(__name__)


def _load_config():
    # Ensure project root imports (src.config) resolve when run as a module.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from src.config import (
        EMBEDDING_DIMENSIONS,
        OPENAI_EMBEDDING_MODEL,
        QDRANT_COLLECTION,
        QDRANT_PATH,
        SECTION0_CACHE_PATH,
    )
    return {
        "embedding_model": OPENAI_EMBEDDING_MODEL,
        "embedding_dims": EMBEDDING_DIMENSIONS,
        "qdrant_path": QDRANT_PATH,
        "collection": QDRANT_COLLECTION,
        "section0_path": SECTION0_CACHE_PATH,
    }


def _write_section0(path: str, section0: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(section0 or "")
    logger.info("Wrote Section 0 cache → %s (%d chars)", path, len(section0 or ""))


def inject(
    kb_dir: str = "KB",
    qdrant_path: str | None = None,
    collection: str | None = None,
    force: bool = True,
) -> int:
    """
    Parse KB and write a fresh local Qdrant index.

    Returns number of documents indexed.
    """
    cfg = _load_config()
    qdrant_path = qdrant_path or cfg["qdrant_path"]
    collection = collection or cfg["collection"]
    section0_path = cfg["section0_path"]

    logger.info("Loading documents from %s ...", kb_dir)
    docs, section0 = load_and_process_documents(kb_dir)
    if not docs:
        raise RuntimeError(f"No documents found under {kb_dir!r}. Nothing to index.")

    _write_section0(section0_path, section0)

    abs_path = os.path.abspath(qdrant_path)
    if force and os.path.exists(abs_path):
        logger.info("Removing existing Qdrant store at %s", abs_path)
        shutil.rmtree(abs_path)

    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

    logger.info(
        "Creating Qdrant at %s (collection=%s, dims=%d)",
        abs_path, collection, cfg["embedding_dims"],
    )
    client = QdrantClient(path=abs_path)
    try:
        if client.collection_exists(collection):
            client.delete_collection(collection)
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=cfg["embedding_dims"],
                distance=Distance.COSINE,
            ),
        )

        embeddings = OpenAIEmbeddings(model=cfg["embedding_model"])
        vectorstore = QdrantVectorStore(
            client=client,
            collection_name=collection,
            embedding=embeddings,
        )
        # Small batches: OpenAI embed + local Qdrant write (path mode is single-process)
        batch_size = 32
        total = len(docs)
        for i in range(0, total, batch_size):
            batch = docs[i : i + batch_size]
            end = min(i + batch_size, total)
            logger.info("Embedding + writing docs %d-%d / %d ...", i + 1, end, total)
            vectorstore.add_documents(batch)
            logger.info("Indexed %d / %d", end, total)
    finally:
        client.close()

    logger.info("Done. Indexed %d docs → %s [%s]", len(docs), abs_path, collection)
    return len(docs)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    parser = argparse.ArgumentParser(description="Index KB/ into local Qdrant")
    parser.add_argument("--kb-dir", default="KB", help="KB source directory")
    parser.add_argument(
        "--qdrant-path",
        default=None,
        help="Local Qdrant folder (default: QDRANT_PATH from config/env)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Collection name (default: QDRANT_COLLECTION from config/env)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=True,
        help="Delete existing local Qdrant folder before indexing (default: True)",
    )
    parser.add_argument(
        "--no-force",
        action="store_true",
        help="Do not delete existing Qdrant folder (may fail if collection exists)",
    )
    args = parser.parse_args(argv)

    force = not args.no_force
    count = inject(
        kb_dir=args.kb_dir,
        qdrant_path=args.qdrant_path,
        collection=args.collection,
        force=force,
    )
    print(f"Indexed {count} documents into local Qdrant.")


if __name__ == "__main__":
    main()
