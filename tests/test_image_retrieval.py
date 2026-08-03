"""Tests for image retrieval layer (get_case_images, search, bundle)."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.services.image_retrieval import (
    get_case_images,
    search_case_images,
    get_case_visual_bundle,
)


def _seed_test_db(db_path: str):
    """Create a minimal test DB with images, articles, and co-retrieval rules."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'current',
            category TEXT DEFAULT '',
            product TEXT DEFAULT '',
            device_type TEXT DEFAULT 'General',
            audience TEXT DEFAULT 'operator',
            intent TEXT DEFAULT '',
            direct_answer TEXT DEFAULT '',
            recommended_steps_json TEXT DEFAULT '[]',
            optional_steps_json TEXT DEFAULT '[]',
            resolution_criteria TEXT DEFAULT '',
            escalation_condition TEXT DEFAULT '',
            evidence_to_collect TEXT DEFAULT '',
            example_phrases_json TEXT DEFAULT '[]',
            raw_body TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS co_retrieval_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_article_id TEXT NOT NULL,
            companion_article_id TEXT NOT NULL,
            rule_text TEXT DEFAULT '',
            UNIQUE(source_article_id, companion_article_id)
        );

        CREATE TABLE IF NOT EXISTS images (
            image_id TEXT PRIMARY KEY,
            source_doc TEXT NOT NULL,
            file_path TEXT NOT NULL,
            checksum TEXT NOT NULL,
            image_type TEXT DEFAULT 'screenshot',
            caption TEXT DEFAULT '',
            visual_summary TEXT DEFAULT '',
            width INTEGER, height INTEGER,
            format TEXT, file_size INTEGER,
            page_number INTEGER, sequence INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS image_case_map (
            image_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            is_primary INTEGER DEFAULT 1,
            PRIMARY KEY (image_id, article_id)
        );

        CREATE TABLE IF NOT EXISTS image_search_terms (
            image_id TEXT NOT NULL,
            term TEXT NOT NULL,
            PRIMARY KEY (image_id, term)
        );

        CREATE TABLE IF NOT EXISTS image_retrieval_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT '',
            query TEXT DEFAULT '',
            article_ids_json TEXT DEFAULT '[]',
            image_ids_json TEXT DEFAULT '[]',
            pages_json TEXT DEFAULT '[]',
            linked_cases_json TEXT DEFAULT '[]',
            reason TEXT DEFAULT '',
            latency_ms REAL DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT INTO articles (article_id, device_type, direct_answer) VALUES
            ('KB-READER-001', 'Card Reader', 'Check cable connection'),
            ('KB-HUB-002', 'Hub', 'Restart the hub'),
            ('KB-POS-003', 'POS', 'Verify network');

        INSERT INTO co_retrieval_rules (source_article_id, companion_article_id) VALUES
            ('KB-READER-001', 'KB-HUB-002');

        INSERT INTO images (image_id, source_doc, file_path, checksum, caption, page_number, sequence, width, height, format, file_size) VALUES
            ('img1', 'v22', '/fake/img1.png', 'cs1', 'Card reader cable view', 5, 1, 400, 300, 'png', 15000),
            ('img2', 'v22', '/fake/img2.png', 'cs2', 'Hub LED status', 8, 1, 500, 400, 'png', 20000),
            ('img3', 'v22', '/fake/img3.png', 'cs3', 'POS network screen', 12, 1, 600, 400, 'png', 25000);

        INSERT INTO image_case_map (image_id, article_id, is_primary) VALUES
            ('img1', 'KB-READER-001', 1),
            ('img2', 'KB-HUB-002', 1),
            ('img3', 'KB-POS-003', 1);

        INSERT INTO image_search_terms (image_id, term) VALUES
            ('img1', 'cable'), ('img1', 'card reader'),
            ('img2', 'hub'), ('img2', 'led'),
            ('img3', 'pos'), ('img3', 'network');
    """)
    conn.commit()
    conn.close()


class TestImageRetrieval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        _seed_test_db(self.db_path)
        self.patcher = patch("src.services.image_retrieval._DB_PATH", self.db_path)
        self.patcher.start()
        self.co_patcher = patch("src.services.image_retrieval._get_conn")
        mock_conn_fn = self.co_patcher.start()
        mock_conn_fn.side_effect = lambda: sqlite3.connect(self.db_path, check_same_thread=False).__enter__() or self._make_conn()

        self.co_patcher.stop()
        self.patcher.stop()

        self.patcher = patch("src.services.image_retrieval._DB_PATH", self.db_path)
        self.patcher.start()

    def _make_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def tearDown(self):
        self.patcher.stop()
        os.unlink(self.db_path)

    @patch("src.services.image_retrieval.expand_co_retrieval")
    def test_get_case_images_primary(self, mock_co):
        from src.services.co_retrieval import CoRetrievalResult
        mock_co.return_value = CoRetrievalResult(companion_ids=["KB-HUB-002"])
        images = get_case_images("KB-READER-001", include_linked=True)
        self.assertTrue(len(images) >= 1)
        primary = [i for i in images if i.get("is_primary")]
        self.assertTrue(len(primary) >= 1)

    @patch("src.services.image_retrieval.expand_co_retrieval")
    def test_get_case_images_with_linked(self, mock_co):
        from src.services.co_retrieval import CoRetrievalResult
        mock_co.return_value = CoRetrievalResult(companion_ids=["KB-HUB-002"])
        images = get_case_images("KB-READER-001", include_linked=True)
        image_ids = [i["image_id"] for i in images]
        self.assertIn("img1", image_ids)
        self.assertIn("img2", image_ids)

    def test_search_case_images(self):
        results = search_case_images("cable card reader")
        self.assertTrue(len(results) >= 1)

    @patch("src.services.image_retrieval.expand_co_retrieval")
    def test_visual_bundle(self, mock_co):
        from src.services.co_retrieval import CoRetrievalResult
        mock_co.return_value = CoRetrievalResult(companion_ids=[])
        bundle = get_case_visual_bundle("KB-READER-001")
        self.assertEqual(bundle["article_id"], "KB-READER-001")
        self.assertIsNotNone(bundle["article"])
        self.assertTrue(bundle["primary_count"] >= 1)


if __name__ == "__main__":
    unittest.main()
