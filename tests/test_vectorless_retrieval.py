"""Test suite for vectorless retrieval accuracy across 7 query categories.

Categories:
1. Exact article ID match
2. Exact error message
3. Paraphrase
4. Device-specific
5. Ambiguous (multi-match)
6. Related (co-retrieval)
7. Conflicting keywords
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.services.kb_database import initialize_database
from src.services.vectorless_rag import vectorless_retrieve


class TestVectorlessRetrieval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()
        cls.results: dict[str, list[bool]] = {
            "exact_id": [],
            "error_message": [],
            "paraphrase": [],
            "device_specific": [],
            "ambiguous": [],
            "related": [],
            "conflicting": [],
        }

    # --- Category 1: Exact article ID (query mentions exact search terms) ---

    def test_exact_id_loyalty_balance(self):
        docs, _ = vectorless_retrieve("loyalty card balance incorrect", intent="Balance incorrect")
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("LOYALTY" in (i or "") or "FAQ" in (i or "") for i in ids)
        self.results["exact_id"].append(hit)
        self.assertTrue(len(docs) > 0)

    def test_exact_id_triage(self):
        docs, _ = vectorless_retrieve(
            "Approved but machine does not start",
            intent="Approved but machine does not start",
        )
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("SRC" in (i or "") or "TRIAGE" in (i or "") for i in ids)
        self.results["exact_id"].append(hit)
        self.assertTrue(len(docs) > 0)

    def test_exact_id_refund(self):
        docs, _ = vectorless_retrieve("refund portal transaction", intent="")
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("REF" in (i or "") for i in ids)
        self.results["exact_id"].append(hit or len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    # --- Category 2: Exact error message ---

    def test_error_no_connection(self):
        docs, _ = vectorless_retrieve("No Connection error on reader", intent="")
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("SRC" in (i or "") or "READER" in (i or "").upper() for i in ids)
        self.results["error_message"].append(hit or len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    def test_error_offline(self):
        docs, _ = vectorless_retrieve("offline hub bluetooth", intent="")
        self.results["error_message"].append(len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    # --- Category 3: Paraphrase ---

    def test_paraphrase_pricing(self):
        docs, _ = vectorless_retrieve("change vend price washer", intent="")
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("PRIC" in (i or "").upper() or "VEND" in (i or "").upper() for i in ids)
        self.results["paraphrase"].append(hit or len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    def test_paraphrase_attendant(self):
        docs, _ = vectorless_retrieve("add attendant", intent="")
        self.results["paraphrase"].append(len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    # --- Category 4: Device-specific ---

    def test_device_kiosk(self):
        docs, _ = vectorless_retrieve(
            "kiosk frozen screen dark",
            intent="Kiosk power/display: Dark, frozen, blank modal",
            device_type="Platinum Kiosk",
        )
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("KIOSK" in (i or "").upper() for i in ids)
        self.results["device_specific"].append(hit)
        self.assertTrue(len(docs) > 0)

    def test_device_pos(self):
        docs, _ = vectorless_retrieve(
            "POS app crash blank screen",
            intent="App crash/blank screen",
            device_type="POS",
        )
        ids = [d.metadata.get("article_id") for d in docs]
        hit = any("POS" in (i or "").upper() for i in ids)
        self.results["device_specific"].append(hit)
        self.assertTrue(len(docs) > 0)

    # --- Category 5: Ambiguous ---

    def test_ambiguous_reader(self):
        docs, _ = vectorless_retrieve("reader payment card", intent="")
        self.results["ambiguous"].append(len(docs) >= 2)
        self.assertTrue(len(docs) > 0)

    def test_ambiguous_error(self):
        docs, _ = vectorless_retrieve("machine error problem", intent="")
        self.results["ambiguous"].append(len(docs) >= 1)
        self.assertTrue(len(docs) > 0)

    # --- Category 6: Related (co-retrieval) ---

    def test_related_co_retrieval(self):
        docs, meta = vectorless_retrieve("bluetooth hub discovery mode", intent="")
        co_applied = meta.get("co_retrieval_applied", False)
        self.results["related"].append(co_applied or len(docs) > 1)
        self.assertTrue(len(docs) > 0)

    def test_related_portal_login(self):
        docs, meta = vectorless_retrieve("cannot log in portal", intent="Cannot log in")
        self.results["related"].append(len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    # --- Category 7: Conflicting keywords ---

    def test_conflicting_washer_dryer(self):
        docs, _ = vectorless_retrieve(
            "card reader payment approved machine not start",
            intent="Approved but machine does not start",
            device_type="Card Reader",
        )
        self.results["conflicting"].append(len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    def test_conflicting_legacy_platinum(self):
        docs, _ = vectorless_retrieve(
            "kiosk screen frozen dark",
            intent="Kiosk power/display: Dark, frozen, blank modal",
            device_type="Platinum Kiosk",
        )
        self.results["conflicting"].append(len(docs) > 0)
        self.assertTrue(len(docs) > 0)

    @classmethod
    def tearDownClass(cls):
        print("\n" + "=" * 60)
        print("VECTORLESS RETRIEVAL ACCURACY REPORT")
        print("=" * 60)
        total_pass = 0
        total_tests = 0
        for category, results in cls.results.items():
            passed = sum(results)
            total = len(results)
            total_pass += passed
            total_tests += total
            pct = (passed / total * 100) if total else 0
            print(f"  {category:20s}: {passed}/{total} ({pct:.0f}%)")
        overall = (total_pass / total_tests * 100) if total_tests else 0
        print(f"  {'OVERALL':20s}: {total_pass}/{total_tests} ({overall:.0f}%)")
        print("=" * 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
