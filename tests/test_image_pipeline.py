"""Unit tests for image extraction pipeline components."""
import unittest
from unittest.mock import patch, MagicMock

from src.services.images.dedupe import deduplicate_images, _should_discard
from src.services.images.extractor import ExtractedImage
from src.services.images.search_terms import extract_search_terms
from src.services.images.captioner import CaptionResult


def _img(checksum="abc123", width=400, height=300, file_size=10000):
    return ExtractedImage(
        file_path="/tmp/test.png",
        page_number=1,
        sequence=1,
        width=width,
        height=height,
        format="png",
        file_size=file_size,
        checksum=checksum,
    )


class TestDedupe(unittest.TestCase):
    def test_duplicate_checksum_removed(self):
        imgs = [_img("aaa"), _img("aaa"), _img("bbb")]
        with patch("src.services.images.dedupe._remove_file"):
            kept = deduplicate_images(imgs)
        self.assertEqual(len(kept), 2)
        checksums = [i.checksum for i in kept]
        self.assertIn("aaa", checksums)
        self.assertIn("bbb", checksums)

    def test_too_small_removed(self):
        img = _img(width=50, height=50)
        reason = _should_discard(img, set())
        self.assertEqual(reason, "too_small")

    def test_tiny_file_removed(self):
        img = _img(file_size=1000)
        reason = _should_discard(img, set())
        self.assertEqual(reason, "tiny_file")

    def test_extreme_aspect_removed(self):
        img = _img(width=2000, height=100, file_size=10000)
        reason = _should_discard(img, set())
        self.assertEqual(reason, "extreme_aspect")

    def test_valid_image_kept(self):
        img = _img(width=400, height=300, file_size=10000, checksum="new")
        reason = _should_discard(img, set())
        self.assertIsNone(reason)


class TestSearchTerms(unittest.TestCase):
    def test_extracts_quoted_terms(self):
        cr = CaptionResult(
            checksum="x",
            caption='Screenshot showing "Connect" button',
            visual_summary='Button labeled "Start Wash" visible',
            image_type="screenshot",
        )
        terms = extract_search_terms(cr)
        self.assertIn("connect", terms)
        self.assertIn("start wash", terms)

    def test_extracts_device_terms(self):
        cr = CaptionResult(
            checksum="x",
            caption="POS terminal showing card reader error",
            visual_summary="Card reader disconnected message",
            image_type="screenshot",
        )
        terms = extract_search_terms(cr)
        self.assertIn("pos", terms)
        self.assertIn("card reader", terms)

    def test_image_type_included(self):
        cr = CaptionResult(
            checksum="x",
            caption="Wiring diagram",
            visual_summary="",
            image_type="diagram",
        )
        terms = extract_search_terms(cr)
        self.assertIn("diagram", terms)


class TestEmptyPage(unittest.TestCase):
    def test_no_content_page(self):
        from src.services.images.empty_page import is_empty_page
        page = MagicMock()
        page.get_text.return_value = ""
        page.get_images.return_value = []
        page.get_drawings.return_value = []
        result = is_empty_page(page)
        self.assertEqual(result, "no_content")

    def test_minimal_content_page(self):
        from src.services.images.empty_page import is_empty_page
        page = MagicMock()
        page.get_text.return_value = "Page 12"
        page.get_images.return_value = []
        page.get_drawings.return_value = [1]
        result = is_empty_page(page)
        self.assertEqual(result, "minimal_content")

    def test_content_page_not_empty(self):
        from src.services.images.empty_page import is_empty_page
        page = MagicMock()
        page.get_text.return_value = "This page has meaningful content about troubleshooting POS devices"
        page.get_images.return_value = [(1, 0, 0, 0, 0, 0, 0)]
        page.get_drawings.return_value = []
        result = is_empty_page(page)
        self.assertIsNone(result)


class TestCaseMapper(unittest.TestCase):
    @patch("src.services.images.case_mapper.fitz")
    def test_v22_page_map(self, mock_fitz):
        from src.services.images.case_mapper import build_v22_page_map

        pages_text = [
            "ARTICLE START: KB-READER-001\nSome content",
            "More content\nARTICLE END: KB-READER-001",
            "ARTICLE START: KB-HUB-002\nHub stuff\nARTICLE END: KB-HUB-002",
        ]

        mock_doc = MagicMock()
        mock_doc.__len__ = lambda s: 3
        mock_doc.__iter__ = lambda s: iter(range(3))
        mock_doc.__getitem__ = lambda s, i: MagicMock(get_text=lambda: pages_text[i])
        mock_fitz.open.return_value = mock_doc

        result = build_v22_page_map("fake.pdf")
        self.assertIn("KB-READER-001", result)
        self.assertEqual(result["KB-READER-001"], (1, 2))
        self.assertIn("KB-HUB-002", result)
        self.assertEqual(result["KB-HUB-002"], (3, 3))


if __name__ == "__main__":
    unittest.main()
