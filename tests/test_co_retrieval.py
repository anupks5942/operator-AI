"""Unit tests for recursive co-retrieval engine."""
import unittest
from unittest.mock import patch

from src.services.co_retrieval import expand_co_retrieval
from src.models.article_schema import CanonicalArticle


def _article(aid: str) -> CanonicalArticle:
    return CanonicalArticle(article_id=aid, direct_answer=f"Answer for {aid}")


class TestExpandCoRetrieval(unittest.TestCase):
    @patch("src.services.co_retrieval.get_article")
    @patch("src.services.co_retrieval.get_companions")
    def test_single_level_companions(self, mock_companions, mock_get_article):
        mock_companions.side_effect = lambda aid: {
            "KB-A": ["KB-B", "KB-C"],
            "KB-B": [],
            "KB-C": [],
        }.get(aid, [])
        mock_get_article.side_effect = lambda aid: _article(aid)

        result = expand_co_retrieval(["KB-A"], max_depth=3)

        self.assertEqual(result.companion_ids, ["KB-B", "KB-C"])
        self.assertEqual(result.depth_by_id["KB-B"], 1)
        self.assertEqual(result.depth_by_id["KB-C"], 1)
        self.assertEqual(result.unresolved_ids, [])

    @patch("src.services.co_retrieval.get_article")
    @patch("src.services.co_retrieval.get_companions")
    def test_multi_level_bfs(self, mock_companions, mock_get_article):
        mock_companions.side_effect = lambda aid: {
            "KB-A": ["KB-B"],
            "KB-B": ["KB-C"],
            "KB-C": [],
        }.get(aid, [])
        mock_get_article.side_effect = lambda aid: _article(aid)

        result = expand_co_retrieval(["KB-A"], max_depth=3)

        self.assertEqual(result.companion_ids, ["KB-B", "KB-C"])
        self.assertEqual(result.depth_by_id["KB-C"], 2)

    @patch("src.services.co_retrieval.get_article")
    @patch("src.services.co_retrieval.get_companions")
    def test_max_depth_stops_traversal(self, mock_companions, mock_get_article):
        mock_companions.side_effect = lambda aid: {
            "KB-A": ["KB-B"],
            "KB-B": ["KB-C"],
            "KB-C": ["KB-D"],
        }.get(aid, [])
        mock_get_article.side_effect = lambda aid: _article(aid)

        result = expand_co_retrieval(["KB-A"], max_depth=2)

        self.assertIn("KB-B", result.companion_ids)
        self.assertIn("KB-C", result.companion_ids)
        self.assertNotIn("KB-D", result.companion_ids)

    @patch("src.services.co_retrieval.get_article")
    @patch("src.services.co_retrieval.get_companions")
    def test_cycle_prevention(self, mock_companions, mock_get_article):
        mock_companions.side_effect = lambda aid: {
            "KB-A": ["KB-B"],
            "KB-B": ["KB-A"],
        }.get(aid, [])
        mock_get_article.side_effect = lambda aid: _article(aid)

        result = expand_co_retrieval(["KB-A"], max_depth=3)

        self.assertEqual(result.companion_ids, ["KB-B"])
        self.assertTrue(any(c[1] == "KB-A" for c in result.cycles_skipped))

    @patch("src.services.co_retrieval.get_article")
    @patch("src.services.co_retrieval.get_companions")
    def test_unresolved_reference(self, mock_companions, mock_get_article):
        mock_companions.side_effect = lambda aid: {
            "KB-A": ["KB-MISSING"],
        }.get(aid, [])
        mock_get_article.side_effect = lambda aid: None if aid == "KB-MISSING" else _article(aid)

        result = expand_co_retrieval(["KB-A"], max_depth=3)

        self.assertEqual(result.unresolved_ids, ["KB-MISSING"])
        self.assertEqual(result.companion_ids, [])

    @patch("src.services.co_retrieval.get_article")
    @patch("src.services.co_retrieval.get_companions")
    def test_dedupe_multiple_children(self, mock_companions, mock_get_article):
        mock_companions.side_effect = lambda aid: {
            "KB-A": ["KB-B", "KB-C"],
            "KB-B": ["KB-D"],
            "KB-C": ["KB-D"],
        }.get(aid, [])
        mock_get_article.side_effect = lambda aid: _article(aid)

        result = expand_co_retrieval(["KB-A"], max_depth=3)

        self.assertEqual(result.companion_ids.count("KB-D"), 1)
        self.assertEqual(set(result.companion_ids), {"KB-B", "KB-C", "KB-D"})


if __name__ == "__main__":
    unittest.main()
