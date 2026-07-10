"""
Regression tests for bug fixes and RAG prompt improvements.
Tests gibberish detection, workflow reminder branching, blast radius inference,
domain typo normalization, and greeting detection.
"""
from __future__ import annotations

import unittest

from src.agent.graph import (
    _is_gibberish,
    _is_conversational_workflow_reply,
)
from src.agent.nodes import (
    workflow_reminder_node,
    _is_kb_gap_response,
    _query_mentions_symptom,
)
from src.agent.router import (
    infer_blast_radius,
    _is_greeting,
    _is_product_overview_query,
)


# ── Gibberish detection ───────────────────────────────────────────────────────

class GibberishDetectionTests(unittest.TestCase):
    def test_keyboard_mash_detected(self) -> None:
        self.assertTrue(_is_gibberish("asdfjksdf"))
        self.assertTrue(_is_gibberish("kjsdhfkj"))
        self.assertTrue(_is_gibberish("qwrtypsdf"))

    def test_short_strings_not_gibberish(self) -> None:
        self.assertFalse(_is_gibberish("hi"))
        self.assertFalse(_is_gibberish("ni"))
        self.assertFalse(_is_gibberish("yaa"))

    def test_real_words_not_gibberish(self) -> None:
        self.assertFalse(_is_gibberish("washer"))
        self.assertFalse(_is_gibberish("machine"))
        self.assertFalse(_is_gibberish("everything"))
        self.assertFalse(_is_gibberish("kiosk"))

    def test_multi_token_never_gibberish(self) -> None:
        self.assertFalse(_is_gibberish("asdf jkl"))
        self.assertFalse(_is_gibberish("3 machine is down"))

    def test_digits_never_gibberish(self) -> None:
        self.assertFalse(_is_gibberish("00000212"))


# ── Workflow reminder branching ───────────────────────────────────────────────

class WorkflowReminderBranchingTests(unittest.TestCase):
    def test_reminder_after_troubleshooting_done(self) -> None:
        state = {
            "messages": [],
            "extracted_entities": {"troubleshooting_done": True},
        }
        result = workflow_reminder_node(state)
        text = result["messages"][0].content.lower()
        self.assertIn("did the troubleshooting steps", text)

    def test_reminder_during_blast_radius_phase(self) -> None:
        state = {
            "messages": [],
            "extracted_entities": {"blast_radius_asked": True},
        }
        result = workflow_reminder_node(state)
        text = result["messages"][0].content.lower()
        self.assertNotIn("did the troubleshooting", text)
        self.assertIn("one specific machine", text)

    def test_reminder_during_clarify_phase(self) -> None:
        state = {
            "messages": [],
            "extracted_entities": {"clarify_asked": True},
        }
        result = workflow_reminder_node(state)
        text = result["messages"][0].content.lower()
        self.assertIn("describe", text)

    def test_reminder_generic_fallback(self) -> None:
        state = {"messages": [], "extracted_entities": {}}
        result = workflow_reminder_node(state)
        text = result["messages"][0].content.lower()
        self.assertIn("rephrase", text)


# ── Blast radius inference ────────────────────────────────────────────────────

class BlastRadiusInferenceTests(unittest.TestCase):
    def test_numeric_count_is_single_machine(self) -> None:
        self.assertEqual(infer_blast_radius("3 machine is down"), "single_machine")
        self.assertEqual(infer_blast_radius("5 machien is down"), "single_machine")
        self.assertEqual(infer_blast_radius("1 washer down"), "single_machine")

    def test_word_form_counts_single_machine(self) -> None:
        self.assertEqual(infer_blast_radius("two machines are down"), "single_machine")
        self.assertEqual(infer_blast_radius("three washers offline"), "single_machine")

    def test_entire_short_variants(self) -> None:
        self.assertEqual(infer_blast_radius("all"), "entire_location")
        self.assertEqual(infer_blast_radius("everything"), "entire_location")


# ── KB gap detection ──────────────────────────────────────────────────────────

class KBGapDetectionTests(unittest.TestCase):
    def test_detects_standard_gap_phrase(self) -> None:
        self.assertTrue(_is_kb_gap_response(
            "I do not have that information in the current KB."
        ))
        self.assertTrue(_is_kb_gap_response(
            "I do not have specific guidance for kiosk beeping in my current knowledge base."
        ))

    def test_normal_answer_not_gap(self) -> None:
        self.assertFalse(_is_kb_gap_response(
            "Power-cycle the SpyderWash Hub for 30 seconds."
        ))

    def test_symptom_detection(self) -> None:
        self.assertTrue(_query_mentions_symptom("washer making loud noise"))
        self.assertTrue(_query_mentions_symptom("green light on machine"))
        self.assertTrue(_query_mentions_symptom("kiosk beeping continuously"))
        self.assertFalse(_query_mentions_symptom("check balance on lc-00000212"))


# ── Greeting detection ────────────────────────────────────────────────────────

class GreetingDetectionTests(unittest.TestCase):
    def test_standard_greetings(self) -> None:
        self.assertTrue(_is_greeting("hi"))
        self.assertTrue(_is_greeting("hello"))
        self.assertTrue(_is_greeting("hola"))

    def test_hindi_greetings(self) -> None:
        self.assertTrue(_is_greeting("namaste"))
        self.assertTrue(_is_greeting("namaskar"))

    def test_arabic_greeting(self) -> None:
        self.assertTrue(_is_greeting("salaam"))

    def test_not_greeting(self) -> None:
        self.assertFalse(_is_greeting("my machine is down"))
        self.assertFalse(_is_greeting("check balance on 00000212"))


class ProductOverviewDetectionTests(unittest.TestCase):
    def test_spyderwash_overview_questions(self) -> None:
        self.assertTrue(_is_product_overview_query("What is SpyderWash?"))
        self.assertTrue(_is_product_overview_query('What is SpyderWash?"'))
        self.assertTrue(_is_product_overview_query("What components does SpyderWash have"))

    def test_not_product_overview(self) -> None:
        self.assertFalse(_is_product_overview_query("my machine is down"))
        self.assertFalse(_is_product_overview_query("check balance on 00000212"))


# ── Conversational reply detection ────────────────────────────────────────────

class ConversationalReplyTests(unittest.TestCase):
    def test_yes_no_conversational(self) -> None:
        self.assertTrue(_is_conversational_workflow_reply("yes"))
        self.assertTrue(_is_conversational_workflow_reply("no"))

    def test_blast_radius_answers_conversational(self) -> None:
        self.assertTrue(_is_conversational_workflow_reply("one machine"))
        self.assertTrue(_is_conversational_workflow_reply("entire location"))

    def test_real_issue_not_conversational(self) -> None:
        self.assertFalse(_is_conversational_workflow_reply("washer is making noise"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
