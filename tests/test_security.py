"""PCI-DSS security helper tests."""
from __future__ import annotations

import unittest

from src.utils.security import (
    contains_prohibited_card_auth_data,
    mask_credit_cards,
    sanitize_outbound_text,
    sanitize_user_text,
)


class MaskCreditCardsTests(unittest.TestCase):
    def test_masks_plain_16_digit_visa(self) -> None:
        result = mask_credit_cards("My card is 4111111111111111 please help")
        self.assertIn("**-**-****-1111", result)
        self.assertNotIn("4111111111111111", result)

    def test_masks_spaced_pan(self) -> None:
        result = mask_credit_cards("4111 1111 1111 1111")
        self.assertEqual(result, "**-**-****-1111")

    def test_masks_amex(self) -> None:
        result = mask_credit_cards("378282246310005")
        self.assertIn("**-**-****-0005", result)
        self.assertNotIn("378282246310005", result)

    def test_does_not_mask_loyalty_card_id(self) -> None:
        text = "Balance on loyalty card 501896"
        self.assertEqual(mask_credit_cards(text), text)

    def test_sanitize_user_text_alias(self) -> None:
        raw = "4111111111111111"
        self.assertEqual(sanitize_user_text(raw), "**-**-****-1111")

    def test_sanitize_outbound_text(self) -> None:
        summary = "Customer paid with 4111111111111111"
        self.assertNotIn("4111111111111111", sanitize_outbound_text(summary))


class ProhibitedCardAuthDataTests(unittest.TestCase):
    def test_detects_cvv_keyword(self) -> None:
        self.assertTrue(contains_prohibited_card_auth_data("The CVV is 123 on the back"))

    def test_detects_security_code(self) -> None:
        self.assertTrue(contains_prohibited_card_auth_data("security code 9999"))

    def test_detects_track_data(self) -> None:
        self.assertTrue(contains_prohibited_card_auth_data("Here is the track 2 data"))

    def test_allows_normal_troubleshooting(self) -> None:
        self.assertFalse(contains_prohibited_card_auth_data("My washer won't start"))

    def test_allows_loyalty_balance(self) -> None:
        self.assertFalse(contains_prohibited_card_auth_data("Check balance for card 501896"))


class PciGraphRoutingTests(unittest.TestCase):
    def test_cvv_message_refused_without_llm(self) -> None:
        from src.agent.graph import create_agent_graph

        graph = create_agent_graph()
        config = {"configurable": {"thread_id": "pci-routing-test"}}
        result = graph.invoke(
            {"messages": [("user", "My CVV is 123 on the back of the card")]},
            config=config,
        )
        reply = result["messages"][-1].content
        self.assertIn("PCI compliance", reply)
        self.assertEqual(result.get("current_intent"), "pci_sensitive_data")


if __name__ == "__main__":
    unittest.main()
