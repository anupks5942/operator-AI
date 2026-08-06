"""
SQLite Knowledge Base Database for structured article storage and retrieval.

Provides:
- Structured article storage with all CanonicalArticle fields
- Co-retrieval rules as explicit relationships
- Device mapping for routing-dimension lookups
- Search term index for keyword matching (Vectorless RAG)
- Retrieval logging for benchmarking
"""
import json
import sqlite3
import os
import logging
from typing import Optional
from src.models.article_schema import CanonicalArticle

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "kb_structured.db"
)
_DB_PATH = os.path.normpath(_DB_PATH)


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_database():
    """Create all tables and indexes if they don't exist."""
    conn = _get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT UNIQUE NOT NULL,
                status TEXT NOT NULL DEFAULT 'current',
                category TEXT NOT NULL DEFAULT '',
                product TEXT NOT NULL DEFAULT '',
                device_type TEXT NOT NULL DEFAULT 'General',
                audience TEXT NOT NULL DEFAULT 'operator',
                intent TEXT NOT NULL DEFAULT '',
                direct_answer TEXT NOT NULL DEFAULT '',
                recommended_steps_json TEXT NOT NULL DEFAULT '[]',
                optional_steps_json TEXT NOT NULL DEFAULT '[]',
                resolution_criteria TEXT NOT NULL DEFAULT '',
                escalation_condition TEXT NOT NULL DEFAULT '',
                evidence_to_collect TEXT NOT NULL DEFAULT '',
                example_phrases_json TEXT NOT NULL DEFAULT '[]',
                raw_body TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS co_retrieval_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_article_id TEXT NOT NULL,
                companion_article_id TEXT NOT NULL,
                rule_text TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (source_article_id) REFERENCES articles(article_id),
                FOREIGN KEY (companion_article_id) REFERENCES articles(article_id),
                UNIQUE(source_article_id, companion_article_id)
            );

            CREATE TABLE IF NOT EXISTS device_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT NOT NULL,
                device_type TEXT NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles(article_id),
                UNIQUE(article_id, device_type)
            );

            CREATE TABLE IF NOT EXISTS search_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT NOT NULL,
                term TEXT NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles(article_id)
            );

            CREATE TABLE IF NOT EXISTS retrieval_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                method TEXT NOT NULL,
                intent TEXT DEFAULT '',
                device_type TEXT DEFAULT '',
                articles_returned_json TEXT NOT NULL DEFAULT '[]',
                scores_json TEXT NOT NULL DEFAULT '[]',
                latency_ms REAL NOT NULL DEFAULT 0,
                co_retrieval_applied INTEGER NOT NULL DEFAULT 0,
                error_type TEXT DEFAULT '',
                empty_result INTEGER DEFAULT 0,
                payload_filter_failed INTEGER DEFAULT 0,
                page_index_leaf TEXT DEFAULT '',
                rejected_ids_json TEXT DEFAULT '[]',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_articles_device_type ON articles(device_type);
            CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
            CREATE INDEX IF NOT EXISTS idx_articles_intent ON articles(intent);
            CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
            CREATE INDEX IF NOT EXISTS idx_search_terms_term ON search_terms(term);
            CREATE INDEX IF NOT EXISTS idx_search_terms_article ON search_terms(article_id);
            CREATE INDEX IF NOT EXISTS idx_co_retrieval_source ON co_retrieval_rules(source_article_id);
            CREATE INDEX IF NOT EXISTS idx_device_mappings_device ON device_mappings(device_type);

            -- Image extraction tables
            CREATE TABLE IF NOT EXISTS images (
                image_id       TEXT PRIMARY KEY,
                stable_id      TEXT UNIQUE,
                source_doc     TEXT NOT NULL,
                file_path      TEXT NOT NULL,
                checksum       TEXT NOT NULL,
                phash          TEXT DEFAULT '',
                image_type     TEXT DEFAULT 'screenshot',
                caption        TEXT DEFAULT '',
                visual_summary TEXT DEFAULT '',
                alt_text       TEXT DEFAULT '',
                width          INTEGER,
                height         INTEGER,
                format         TEXT,
                file_size      INTEGER,
                page_number    INTEGER,
                sequence       INTEGER,
                review_status  TEXT DEFAULT 'approved',
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS image_case_map (
                image_id   TEXT NOT NULL,
                article_id TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (image_id, article_id),
                FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS image_search_terms (
                image_id TEXT NOT NULL,
                term     TEXT NOT NULL,
                PRIMARY KEY (image_id, term),
                FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS image_caption_cache (
                checksum       TEXT PRIMARY KEY,
                caption        TEXT NOT NULL,
                visual_summary TEXT NOT NULL,
                model          TEXT NOT NULL,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pdf_page_skip_log (
                source_doc  TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                reason      TEXT NOT NULL,
                logged_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source_doc, page_number)
            );

            CREATE TABLE IF NOT EXISTS image_retrieval_logs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id        TEXT DEFAULT '',
                query             TEXT DEFAULT '',
                article_ids_json  TEXT DEFAULT '[]',
                image_ids_json    TEXT DEFAULT '[]',
                pages_json        TEXT DEFAULT '[]',
                linked_cases_json TEXT DEFAULT '[]',
                reason            TEXT DEFAULT '',
                latency_ms        REAL DEFAULT 0,
                timestamp         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_images_source ON images(source_doc);
            CREATE INDEX IF NOT EXISTS idx_images_page ON images(source_doc, page_number);
            CREATE INDEX IF NOT EXISTS idx_images_checksum ON images(checksum);
            CREATE INDEX IF NOT EXISTS idx_image_case_article ON image_case_map(article_id);
            CREATE INDEX IF NOT EXISTS idx_image_search_term ON image_search_terms(term);

            -- Image Asset Registry (Brandon v2.3)
            CREATE TABLE IF NOT EXISTS image_asset_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_doc TEXT NOT NULL DEFAULT 'v2.3',
                version TEXT NOT NULL DEFAULT '2.3',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS image_registry_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                UNIQUE(image_id, article_id)
            );

            CREATE INDEX IF NOT EXISTS idx_registry_image_id
                ON image_asset_registry(image_id);
            CREATE INDEX IF NOT EXISTS idx_registry_articles_image
                ON image_registry_articles(image_id);
            CREATE INDEX IF NOT EXISTS idx_registry_articles_article
                ON image_registry_articles(article_id);

            -- PageIndex tree (hierarchical routing)
            CREATE TABLE IF NOT EXISTS page_index_nodes (
                node_id TEXT PRIMARY KEY,
                parent_id TEXT,
                level TEXT NOT NULL,
                label TEXT NOT NULL,
                article_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_page_index_parent
                ON page_index_nodes(parent_id);
            CREATE INDEX IF NOT EXISTS idx_page_index_article
                ON page_index_nodes(article_id);
        """)
        conn.commit()
        logger.info("[KB_DB] Database initialized at %s", _DB_PATH)
    finally:
        conn.close()


def upsert_article(article: CanonicalArticle):
    """Insert or update a canonical article in the database."""
    conn = _get_connection()
    try:
        conn.execute("""
            INSERT INTO articles (
                article_id, status, category, product, device_type, audience, intent,
                direct_answer, recommended_steps_json, optional_steps_json,
                resolution_criteria, escalation_condition, evidence_to_collect,
                example_phrases_json, raw_body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                status=excluded.status,
                category=excluded.category,
                product=excluded.product,
                device_type=excluded.device_type,
                audience=excluded.audience,
                intent=excluded.intent,
                direct_answer=excluded.direct_answer,
                recommended_steps_json=excluded.recommended_steps_json,
                optional_steps_json=excluded.optional_steps_json,
                resolution_criteria=excluded.resolution_criteria,
                escalation_condition=excluded.escalation_condition,
                evidence_to_collect=excluded.evidence_to_collect,
                example_phrases_json=excluded.example_phrases_json,
                raw_body=excluded.raw_body
        """, (
            article.article_id,
            article.status,
            article.category,
            article.product,
            article.device_type,
            article.audience,
            article.intent,
            article.direct_answer,
            json.dumps(article.recommended_steps),
            json.dumps(article.optional_steps),
            article.resolution_criteria,
            article.escalation_condition,
            article.evidence_to_collect,
            json.dumps(article.example_phrases),
            article.raw_body,
        ))

        # Upsert search terms
        conn.execute("DELETE FROM search_terms WHERE article_id = ?", (article.article_id,))
        for term in article.search_terms:
            conn.execute(
                "INSERT INTO search_terms (article_id, term) VALUES (?, ?)",
                (article.article_id, term.lower()),
            )

        # Upsert device mapping
        conn.execute("DELETE FROM device_mappings WHERE article_id = ?", (article.article_id,))
        if article.device_type:
            conn.execute(
                "INSERT OR IGNORE INTO device_mappings (article_id, device_type) VALUES (?, ?)",
                (article.article_id, article.device_type),
            )

        # Co-retrieval rules are inserted separately after all articles exist
        # (to avoid FK constraint failures on forward references)

        conn.commit()
    finally:
        conn.close()


def upsert_co_retrieval_rules(articles: list[CanonicalArticle]):
    """Insert co-retrieval rules after all articles have been inserted."""
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM co_retrieval_rules")
        for article in articles:
            for companion_id in article.co_retrieval_ids:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO co_retrieval_rules (source_article_id, companion_article_id, rule_text) VALUES (?, ?, ?)",
                        (article.article_id, companion_id, f"Retrieve {companion_id} with {article.article_id}"),
                    )
                except sqlite3.IntegrityError:
                    logger.warning(
                        "[KB_DB] Skipping co-retrieval rule %s -> %s (companion not in DB)",
                        article.article_id, companion_id,
                    )
        conn.commit()
        count = conn.execute("SELECT COUNT(*) as cnt FROM co_retrieval_rules").fetchone()["cnt"]
        logger.info("[KB_DB] Inserted %d co-retrieval rules", count)
    finally:
        conn.close()


def get_article(article_id: str) -> Optional[CanonicalArticle]:
    """Fetch a single article by ID."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM articles WHERE article_id = ?", (article_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_article(row)
    finally:
        conn.close()


def get_companions(article_id: str) -> list[str]:
    """Get companion article IDs for co-retrieval."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT companion_article_id FROM co_retrieval_rules WHERE source_article_id = ?",
            (article_id,),
        ).fetchall()
        return [row["companion_article_id"] for row in rows]
    finally:
        conn.close()


def search_by_intent_and_device(
    intent: str,
    device_type: str = "",
    limit: int = 10,
) -> list[CanonicalArticle]:
    """Vectorless retrieval: find articles by intent/category and device_type."""
    conn = _get_connection()
    try:
        # Try exact intent match first
        query = "SELECT * FROM articles WHERE status = 'current'"
        params: list = []

        if intent:
            query += " AND (LOWER(intent) LIKE ? OR LOWER(category) LIKE ?)"
            params.append(f"%{intent.lower()}%")
            params.append(f"%{intent.lower()}%")

        if device_type:
            query += " AND (device_type = ? OR device_type = 'General')"
            params.append(device_type)

        query += " LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [_row_to_article(row) for row in rows]
    finally:
        conn.close()


def search_by_keywords(
    keywords: list[str],
    device_type: str = "",
    limit: int = 10,
) -> list[CanonicalArticle]:
    """Vectorless retrieval: find articles by keyword match on search_terms.

    Terms are stored as semicolon-delimited strings, so we use LIKE matching
    to find rows containing any of the keywords.
    """
    conn = _get_connection()
    try:
        if not keywords:
            return []

        like_clauses = " OR ".join(["st.term LIKE ?"] * len(keywords))
        query = f"""
            SELECT a.*, COUNT(DISTINCT st.term) as match_count
            FROM articles a
            JOIN search_terms st ON a.article_id = st.article_id
            WHERE ({like_clauses})
        """
        params: list = [f"%{k.lower()}%" for k in keywords]

        if device_type:
            query += " AND a.device_type = ?"
            params.append(device_type)

        query += " GROUP BY a.article_id ORDER BY match_count DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [_row_to_article(row) for row in rows]
    finally:
        conn.close()


def log_retrieval(
    query: str,
    method: str,
    intent: str = "",
    device_type: str = "",
    articles_returned: list[str] = None,
    scores: list[float] = None,
    latency_ms: float = 0,
    co_retrieval_applied: bool = False,
    error_type: str = "",
    empty_result: bool = False,
    payload_filter_failed: bool = False,
    page_index_leaf: str = "",
    rejected_ids: list[str] = None,
):
    """Log a retrieval event for benchmarking and monitoring."""
    conn = _get_connection()
    try:
        conn.execute("""
            INSERT INTO retrieval_logs
            (query, method, intent, device_type, articles_returned_json, scores_json,
             latency_ms, co_retrieval_applied, error_type, empty_result, payload_filter_failed,
             page_index_leaf, rejected_ids_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            query,
            method,
            intent,
            device_type,
            json.dumps(articles_returned or []),
            json.dumps(scores or []),
            latency_ms,
            1 if co_retrieval_applied else 0,
            error_type,
            1 if empty_result else 0,
            1 if payload_filter_failed else 0,
            page_index_leaf,
            json.dumps(rejected_ids or []),
        ))
        conn.commit()
    finally:
        conn.close()


def get_retrieval_diagnostics_24h() -> dict:
    """Get retrieval monitoring stats for the last 24 hours."""
    conn = _get_connection()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_queries,
                SUM(CASE WHEN empty_result = 1 THEN 1 ELSE 0 END) as empty_results,
                SUM(CASE WHEN error_type != '' THEN 1 ELSE 0 END) as errors,
                SUM(CASE WHEN payload_filter_failed = 1 THEN 1 ELSE 0 END) as filter_failures,
                AVG(latency_ms) as avg_latency
            FROM retrieval_logs
            WHERE timestamp >= datetime('now', '-24 hours')
        """).fetchone()

        total = row[0] or 0
        return {
            "total_queries_24h": total,
            "empty_search_rate_24h": round((row[1] or 0) / max(total, 1) * 100, 2),
            "error_rate_24h": round((row[2] or 0) / max(total, 1) * 100, 2),
            "payload_filter_failure_rate_24h": round((row[3] or 0) / max(total, 1) * 100, 2),
            "avg_latency_ms_24h": round(row[4] or 0, 2),
        }
    finally:
        conn.close()


def get_article_count() -> int:
    """Return total article count."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM articles").fetchone()
        return row["cnt"]
    finally:
        conn.close()


def _row_to_article(row: sqlite3.Row) -> CanonicalArticle:
    """Convert a database row to a CanonicalArticle."""
    return CanonicalArticle(
        article_id=row["article_id"],
        status=row["status"],
        category=row["category"],
        product=row["product"],
        device_type=row["device_type"],
        audience=row["audience"],
        intent=row["intent"],
        direct_answer=row["direct_answer"],
        recommended_steps=json.loads(row["recommended_steps_json"]),
        optional_steps=json.loads(row["optional_steps_json"]),
        resolution_criteria=row["resolution_criteria"],
        escalation_condition=row["escalation_condition"],
        evidence_to_collect=row["evidence_to_collect"],
        example_phrases=json.loads(row["example_phrases_json"]),
        co_retrieval_ids=[],
        search_terms=[],
        raw_body=row["raw_body"],
    )
