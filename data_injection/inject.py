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
import sqlite3
import sys

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PayloadSchemaType, PointStruct, SparseVector, VectorParams

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
        from src.config import RAG_SPARSE_HYBRID_ENABLED
        sparse_enabled = RAG_SPARSE_HYBRID_ENABLED

        if client.collection_exists(collection):
            client.delete_collection(collection)

        if sparse_enabled:
            from qdrant_client.http.models import SparseVectorParams as SVP
            client.create_collection(
                collection_name=collection,
                vectors_config={
                    "dense": VectorParams(size=cfg["embedding_dims"], distance=Distance.COSINE),
                },
                sparse_vectors_config={
                    "sparse_bm25": SVP(),
                },
            )
            logger.info("Created collection with dense + sparse_bm25 named vectors")
        else:
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=cfg["embedding_dims"],
                    distance=Distance.COSINE,
                ),
            )

        _INDEXED_FIELDS = {
            "metadata.article_id": PayloadSchemaType.KEYWORD,
            "metadata.category": PayloadSchemaType.KEYWORD,
            "metadata.intent": PayloadSchemaType.KEYWORD,
            "metadata.device_type": PayloadSchemaType.KEYWORD,
            "metadata.product": PayloadSchemaType.KEYWORD,
            "metadata.audience": PayloadSchemaType.KEYWORD,
            "metadata.status": PayloadSchemaType.KEYWORD,
            "metadata.source_priority": PayloadSchemaType.INTEGER,
        }
        for field, schema_type in _INDEXED_FIELDS.items():
            client.create_payload_index(collection, field, schema_type)
            logger.info("Created payload index: %s (%s)", field, schema_type.name)

        if sparse_enabled:
            _inject_with_sparse(client, collection, docs, cfg)
        else:
            _inject_dense_only(client, collection, docs, cfg)
    finally:
        client.close()

    logger.info("Done. Indexed %d docs → %s [%s]", len(docs), abs_path, collection)

    # Populate PageIndex tree from article metadata
    _populate_page_index(docs)

    return len(docs)


def _populate_page_index(docs) -> None:
    """Build the PageIndex hierarchical tree from article metadata.

    Levels: root -> part -> category -> product -> article
    Stored in page_index_nodes table.
    """
    from src.services.kb_database import _DB_PATH, initialize_database
    initialize_database()

    conn = sqlite3.connect(_DB_PATH)
    try:
        conn.execute("DELETE FROM page_index_nodes")

        conn.execute(
            "INSERT OR IGNORE INTO page_index_nodes (node_id, parent_id, level, label, article_id) "
            "VALUES ('root', NULL, 'root', 'SpyderWash KB', NULL)"
        )

        seen_parts: set[str] = set()
        seen_categories: set[str] = set()
        seen_products: set[str] = set()

        for doc in docs:
            meta = doc.metadata
            article_id = meta.get("article_id", "")
            category = meta.get("category", "general")
            product = meta.get("product", "general")

            if not article_id:
                continue

            part_prefix = article_id.split("-")[1] if "-" in article_id else "MISC"
            part_id = f"part_{part_prefix}"
            if part_id not in seen_parts:
                seen_parts.add(part_id)
                conn.execute(
                    "INSERT OR IGNORE INTO page_index_nodes (node_id, parent_id, level, label, article_id) "
                    "VALUES (?, 'root', 'part', ?, NULL)",
                    (part_id, f"Part: {part_prefix}"),
                )

            cat_id = f"cat_{part_prefix}_{category.replace(' ', '_')}"
            if cat_id not in seen_categories:
                seen_categories.add(cat_id)
                conn.execute(
                    "INSERT OR IGNORE INTO page_index_nodes (node_id, parent_id, level, label, article_id) "
                    "VALUES (?, ?, 'category', ?, NULL)",
                    (cat_id, part_id, category),
                )

            prod_id = f"prod_{part_prefix}_{category.replace(' ', '_')}_{product.replace(' ', '_')}"
            if prod_id not in seen_products:
                seen_products.add(prod_id)
                conn.execute(
                    "INSERT OR IGNORE INTO page_index_nodes (node_id, parent_id, level, label, article_id) "
                    "VALUES (?, ?, 'product', ?, NULL)",
                    (prod_id, cat_id, product),
                )

            conn.execute(
                "INSERT OR IGNORE INTO page_index_nodes (node_id, parent_id, level, label, article_id) "
                "VALUES (?, ?, 'article', ?, ?)",
                (f"leaf_{article_id}", prod_id, article_id, article_id),
            )

        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM page_index_nodes").fetchone()[0]
        logger.info("[PAGE_INDEX] Populated %d nodes in page_index_nodes", count)
    finally:
        conn.close()


def _inject_dense_only(client: QdrantClient, collection: str, docs, cfg: dict) -> None:
    """Standard dense-only ingestion via LangChain QdrantVectorStore."""
    embeddings = OpenAIEmbeddings(model=cfg["embedding_model"])
    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=collection,
        embedding=embeddings,
    )
    batch_size = 32
    total = len(docs)
    for i in range(0, total, batch_size):
        batch = docs[i : i + batch_size]
        end = min(i + batch_size, total)
        logger.info("Embedding + writing docs %d-%d / %d ...", i + 1, end, total)
        vectorstore.add_documents(batch)
        logger.info("Indexed %d / %d", end, total)


def _inject_with_sparse(client: QdrantClient, collection: str, docs, cfg: dict) -> None:
    """Sparse hybrid ingestion — dense + BM25 sparse vectors per document."""
    import uuid
    from src.services.sparse_hybrid import get_bm25_embedder, compute_sparse_vector

    embeddings_model = OpenAIEmbeddings(model=cfg["embedding_model"])
    bm25 = get_bm25_embedder()

    batch_size = 32
    total = len(docs)

    for i in range(0, total, batch_size):
        batch = docs[i : i + batch_size]
        end = min(i + batch_size, total)
        logger.info("[SPARSE] Embedding + writing docs %d-%d / %d ...", i + 1, end, total)

        texts = [doc.page_content for doc in batch]
        dense_vectors = embeddings_model.embed_documents(texts)

        points = []
        for j, doc in enumerate(batch):
            sparse_vec = compute_sparse_vector(bm25, doc.page_content)
            point = PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dense_vectors[j],
                    "sparse_bm25": sparse_vec,
                },
                payload={
                    "page_content": doc.page_content,
                    "metadata": doc.metadata,
                },
            )
            points.append(point)

        client.upsert(collection_name=collection, points=points)
        logger.info("[SPARSE] Indexed %d / %d", end, total)


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
