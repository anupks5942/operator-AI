"""
Automated TC1 + TC2 outage workflow tests (no Streamlit required).

Mocks the LLM router and RAG service so tests run deterministically without API keys.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from src.agent.graph import (
    _extract_escalation_context,
    _format_conversation_for_email,
    create_agent_graph,
    infer_blast_radius,
)
from src.services.notifications import EscalationResult, NotificationService


def _last_ai_text(state: dict) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
            return str(msg.content).strip()
    return ""


def _invoke_turn(graph, thread_id: str, user_text: str) -> dict:
    config = {"configurable": {"thread_id": thread_id}}
    accumulated: dict = {"messages": []}
    for chunk in graph.stream(
        {"messages": [HumanMessage(content=user_text)]},
        config=config,
        stream_mode="updates",
    ):
        for _node, delta in chunk.items():
            for key, value in delta.items():
                if key == "messages":
                    existing = accumulated.get("messages", [])
                    accumulated["messages"] = existing + (
                        value if isinstance(value, list) else [value]
                    )
                else:
                    accumulated[key] = value
    return accumulated


# Canned router outputs matching Gemini test-case turns.
ROUTER_SCRIPT: list[dict] = [
    # TC1.1
    {
        "current_intent": "machines_not_starting",
        "hardware_lookup_attempted": False,
        "escalation_required": False,
        "api_action_required": False,
        "extracted_entities": {},
        "blast_radius": None,
        "troubleshooting_failed": None,
    },
    # TC1.2
    {
        "current_intent": "machines_not_starting",
        "hardware_lookup_attempted": False,
        "escalation_required": False,
        "api_action_required": False,
        "extracted_entities": {"blast_radius": "single_machine"},
        "blast_radius": "single_machine",
        "troubleshooting_failed": False,
    },
    # TC1.3
    {
        "current_intent": "machines_not_starting",
        "hardware_lookup_attempted": False,
        "escalation_required": False,
        "api_action_required": False,
        "extracted_entities": {
            "blast_radius": "single_machine",
            "troubleshooting_done": True,
            "troubleshooting_failed": False,
        },
        "blast_radius": "single_machine",
        "troubleshooting_failed": False,
    },
    # TC2.1 — simulates router fresh-outage reset (clears stale troubleshooting_done)
    {
        "current_intent": "emergency_store_down",
        "hardware_lookup_attempted": False,
        "escalation_required": True,
        "api_action_required": False,
        "extracted_entities": {
            "blast_radius": "entire_location",
            "troubleshooting_done": False,
            "troubleshooting_failed": False,
        },
        "blast_radius": "entire_location",
        "troubleshooting_failed": False,
    },
    # TC2.2
    {
        "current_intent": "emergency_store_down",
        "hardware_lookup_attempted": False,
        "escalation_required": True,
        "api_action_required": False,
        "extracted_entities": {
            "blast_radius": "entire_location",
            "troubleshooting_done": True,
            "troubleshooting_failed": True,
        },
        "blast_radius": "entire_location",
        "troubleshooting_failed": True,
    },
    # Post-escalation: wait yes
    {
        "current_intent": "general_query",
        "hardware_lookup_attempted": False,
        "escalation_required": False,
        "api_action_required": False,
        "extracted_entities": {},
        "blast_radius": None,
        "troubleshooting_failed": None,
    },
    # Post-escalation: resolved
    {
        "current_intent": "general_query",
        "hardware_lookup_attempted": False,
        "escalation_required": False,
        "api_action_required": False,
        "extracted_entities": {},
        "blast_radius": None,
        "troubleshooting_failed": False,
    },
]


class OutageWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._router_iter = iter(ROUTER_SCRIPT)

        def _mock_router(_state):
            return next(self._router_iter)

        self._rag_patcher = patch("src.agent.graph.RAGService")
        mock_rag_cls = self._rag_patcher.start()
        mock_rag_cls.return_value.query.return_value = {
            "answer": (
                "Power-cycle the SpyderWash Hub for 30 seconds and verify the Ethernet "
                "cable is seated. Check the hub LED for a solid green connection."
            ),
            "context": [],
        }
        self._nodes_rag_patcher = patch(
            "src.agent.nodes.get_rag_service",
            return_value=mock_rag_cls.return_value,
        )
        self._nodes_rag_patcher.start()

        self._router_patcher = patch("src.agent.graph.semantic_router", side_effect=_mock_router)
        self._router_patcher.start()

        self._escalation_patcher = patch.object(
            NotificationService,
            "send_escalation",
            return_value=EscalationResult(email_sent=True, sms_sent=True),
        )
        self._mock_send_escalation = self._escalation_patcher.start()

        self.graph = create_agent_graph()
        self.thread_id = "test-outage-workflow"

    def tearDown(self) -> None:
        self._nodes_rag_patcher.stop()
        self._rag_patcher.stop()
        self._router_patcher.stop()
        self._escalation_patcher.stop()

    def test_tc1_happy_path_no_escalation(self) -> None:
        r1 = _invoke_turn(self.graph, self.thread_id, "My washer won't start.")
        t1 = _last_ai_text(r1)
        self.assertIn("entire laundromat offline", t1.lower())
        self.assertNotIn("harness", t1.lower())
        self.assertEqual(self._mock_send_escalation.call_count, 0)

        r2 = _invoke_turn(self.graph, self.thread_id, "Just one machine.")
        t2 = _last_ai_text(r2)
        self.assertIn("did this resolve the issue", t2.lower())
        self.assertIn("hub", t2.lower())
        self.assertEqual(self._mock_send_escalation.call_count, 0)

        r3 = _invoke_turn(self.graph, self.thread_id, "Yes, that fixed it.")
        t3 = _last_ai_text(r3)
        self.assertIn("glad to hear", t3.lower())
        self.assertEqual(self._mock_send_escalation.call_count, 0)

    def test_tc2_troubleshoot_then_escalate_same_session(self) -> None:
        _invoke_turn(self.graph, self.thread_id, "My washer won't start.")
        _invoke_turn(self.graph, self.thread_id, "Just one machine.")
        _invoke_turn(self.graph, self.thread_id, "Yes, that fixed it.")

        r4 = _invoke_turn(
            self.graph, self.thread_id, "Everything is down at the Chetu Test Location!"
        )
        t4 = _last_ai_text(r4)
        self.assertIn("did this resolve the issue", t4.lower())
        self.assertNotIn("entire laundromat offline", t4.lower())
        self.assertEqual(self._mock_send_escalation.call_count, 0)

        r5 = _invoke_turn(
            self.graph,
            self.thread_id,
            "No, I checked the gateway and it's still completely offline.",
        )
        t5 = _last_ai_text(r5)
        self.assertIn("critical escalation ticket", t5.lower())
        self.assertTrue(r5.get("escalation_dispatched"))
        self.assertEqual(self._mock_send_escalation.call_count, 1)

        _kwargs = self._mock_send_escalation.call_args.kwargs
        self.assertIn("Everything is down at the Chetu Test Location!", _kwargs["summary"])
        self.assertIn("gateway", _kwargs["summary"].lower())
        self.assertIn("Everything is down at the Chetu Test Location!", _kwargs["conversation"])
        self.assertNotIn("washer won't start", _kwargs["summary"].lower())

    def test_post_escalation_followups(self) -> None:
        _invoke_turn(self.graph, self.thread_id, "My washer won't start.")
        _invoke_turn(self.graph, self.thread_id, "Just one machine.")
        _invoke_turn(self.graph, self.thread_id, "Yes, that fixed it.")
        _invoke_turn(self.graph, self.thread_id, "Everything is down at the Chetu Test Location!")
        _invoke_turn(
            self.graph,
            self.thread_id,
            "No, I checked the gateway and it's still completely offline.",
        )

        r6 = _invoke_turn(self.graph, self.thread_id, "wait yes")
        t6 = _last_ai_text(r6)
        self.assertIn("already been dispatched", t6.lower())
        self.assertNotIn("entire laundromat offline", t6.lower())

        r7 = _invoke_turn(self.graph, self.thread_id, "the issue resolved bro")
        t7 = _last_ai_text(r7)
        # With multi-ticket support, resolution may ask which ticket to resolve.
        # Either direct resolution or disambiguation is acceptable.
        self.assertTrue(
            "glad to hear" in t7.lower() or "which ticket" in t7.lower(),
            f"Expected resolution or ticket disambiguation, got: {t7}",
        )


class OutageHelperTests(unittest.TestCase):
    def test_infer_blast_radius_entire_location(self) -> None:
        self.assertEqual(
            infer_blast_radius("Everything is down at the Chetu Test Location!"),
            "entire_location",
        )

    def test_escalation_context_uses_current_incident(self) -> None:
        msgs = [
            HumanMessage(content="My washer won't start."),
            AIMessage(content="Glad to hear the issue is resolved!"),
            HumanMessage(content="Everything is down at the Chetu Test Location!"),
            HumanMessage(content="No, I checked the gateway and it's still completely offline."),
        ]
        ctx = _extract_escalation_context(msgs)
        self.assertIn("Everything is down", ctx)
        self.assertIn("gateway", ctx.lower())
        self.assertNotIn("washer", ctx.lower())

    def test_format_conversation_for_email(self) -> None:
        msgs = [
            HumanMessage(content="Everything is down!"),
            AIMessage(content="Did this resolve the issue? (Yes/No)"),
            HumanMessage(content="No, still offline."),
        ]
        transcript = _format_conversation_for_email(msgs)
        self.assertIn("Operator: Everything is down!", transcript)
        self.assertIn("Agent: Did this resolve the issue?", transcript)
        self.assertIn("Operator: No, still offline.", transcript)


class NotificationServiceTests(unittest.TestCase):
    @patch("src.services.notifications.USE_LIVE_NOTIFICATIONS", False)
    @patch.object(NotificationService, "send_email_html", return_value=True)
    @patch.object(NotificationService, "send_sms", return_value=True)
    def test_send_escalation_mock_mode(self, mock_sms, mock_email) -> None:
        result = NotificationService.send_escalation(
            ticket_id="TKT-TEST1234",
            name="Test Operator",
            email="test@example.com",
            phone="+15551234567",
            conversation="Operator: help\nAgent: troubleshooting",
            summary="Store is down",
        )
        self.assertTrue(result.email_sent)
        self.assertTrue(result.sms_sent)
        mock_email.assert_called_once()
        mock_sms.assert_called_once()
        subject = mock_email.call_args[0][1]
        self.assertIn("SpyderWash Operator Escalation - Test Operator", subject)


if __name__ == "__main__":
    unittest.main(verbosity=2)
