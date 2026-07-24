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

        from unittest.mock import MagicMock
        mock_rag = MagicMock()
        mock_rag.query.return_value = {
            "answer": (
                "Power-cycle the SpyderWash Hub for 30 seconds and verify the Ethernet "
                "cable is seated. Check the hub LED for a solid green connection."
            ),
            "context": [],
        }
        self._nodes_rag_patcher = patch(
            "src.agent.nodes.get_rag_service",
            return_value=mock_rag,
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

        # entire_location auto-escalates without troubleshooting (per AGENTS.md)
        r4 = _invoke_turn(
            self.graph, self.thread_id, "Everything is down at the Chetu Test Location!"
        )
        t4 = _last_ai_text(r4)
        self.assertIn("escalation ticket", t4.lower())
        self.assertEqual(self._mock_send_escalation.call_count, 1)

        _kwargs = self._mock_send_escalation.call_args.kwargs
        self.assertIn("Everything is down at the Chetu Test Location!", _kwargs["summary"])
        self.assertIn("Everything is down at the Chetu Test Location!", _kwargs["conversation"])
        self.assertNotIn("washer won't start", _kwargs["summary"].lower())

    def test_post_escalation_followups(self) -> None:
        _invoke_turn(self.graph, self.thread_id, "My washer won't start.")
        _invoke_turn(self.graph, self.thread_id, "Just one machine.")
        _invoke_turn(self.graph, self.thread_id, "Yes, that fixed it.")
        # entire_location auto-escalates — ticket dispatched immediately
        _invoke_turn(self.graph, self.thread_id, "Everything is down at the Chetu Test Location!")
        self.assertEqual(self._mock_send_escalation.call_count, 1)

        r5 = _invoke_turn(self.graph, self.thread_id, "wait yes")
        t5 = _last_ai_text(r5)
        self.assertIn("dispatched", t5.lower())

        r6 = _invoke_turn(self.graph, self.thread_id, "the issue resolved bro")
        t6 = _last_ai_text(r6)
        self.assertTrue(
            "glad to hear" in t6.lower() or "which ticket" in t6.lower(),
            f"Expected resolution or ticket disambiguation, got: {t6}",
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
        self.assertIn("SpyderWash Escalation TKT-TEST1234", subject)


class PostEscalationFlowTests(unittest.TestCase):
    """Tests for resolve-prompt guarantee, context-aware ack, and dedup guard."""

    def _build_graph(self, router_script, rag_answer=None):
        """Helper to build a fresh graph with mocked router and RAG."""
        from unittest.mock import MagicMock
        self._router_iter = iter(router_script)

        def _mock_router(_state):
            return next(self._router_iter)

        mock_rag = MagicMock()
        mock_rag.query.return_value = {
            "answer": rag_answer or "Check the device and restart the unit.",
            "context": [],
        }
        self._nodes_rag_patcher = patch(
            "src.agent.nodes.get_rag_service",
            return_value=mock_rag,
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

        self._resolution_patcher = patch.object(
            NotificationService,
            "send_resolution",
            return_value=True,
        )
        self._resolution_patcher.start()

        return create_agent_graph()

    def tearDown(self) -> None:
        for p in ("_nodes_rag_patcher", "_router_patcher",
                   "_escalation_patcher", "_resolution_patcher"):
            patcher = getattr(self, p, None)
            if patcher:
                patcher.stop()

    # --- Resolve prompt tests ---

    def test_resolve_prompt_on_technical_support(self) -> None:
        """technical_support intent + RAG answer with 1 marker still gets resolve prompt."""
        script = [{
            "current_intent": "technical_support",
            "hardware_lookup_attempted": False,
            "escalation_required": False,
            "api_action_required": False,
            "extracted_entities": {},
            "blast_radius": None,
            "troubleshooting_failed": None,
        }]
        graph = self._build_graph(script, rag_answer="Check the device and restart the unit.")
        r = _invoke_turn(graph, "test-resolve-ts", "Printer is not working")
        t = _last_ai_text(r)
        self.assertIn("did this resolve the issue", t.lower())

    def test_resolve_prompt_on_kiosk_not_responding(self) -> None:
        """kiosk_not_responding intent always gets resolve prompt."""
        script = [{
            "current_intent": "kiosk_not_responding",
            "hardware_lookup_attempted": False,
            "escalation_required": False,
            "api_action_required": False,
            "extracted_entities": {},
            "blast_radius": None,
            "troubleshooting_failed": None,
        }]
        graph = self._build_graph(script, rag_answer="Power-cycle the kiosk.")
        r = _invoke_turn(graph, "test-resolve-kiosk", "Kiosk is frozen")
        t = _last_ai_text(r)
        self.assertIn("did this resolve the issue", t.lower())

    def test_general_query_no_resolve_prompt(self) -> None:
        """general_query with pure info answer does NOT get resolve prompt."""
        script = [{
            "current_intent": "general_query",
            "hardware_lookup_attempted": False,
            "escalation_required": False,
            "api_action_required": False,
            "extracted_entities": {},
            "blast_radius": None,
            "troubleshooting_failed": None,
        }]
        graph = self._build_graph(script, rag_answer="Attendants can be added in the portal under the Attendant tab.")
        r = _invoke_turn(graph, "test-no-resolve-gq", "How do I add an attendant?")
        t = _last_ai_text(r)
        self.assertNotIn("did this resolve the issue", t.lower())

    # --- Post-escalation context-aware ack tests ---

    def test_post_escalation_callback_request(self) -> None:
        """After ticket dispatch, sharing a phone number gets a callback confirmation."""
        script = [
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": False, "troubleshooting_failed": False},
             "blast_radius": "entire_location", "troubleshooting_failed": False},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "entire_location", "troubleshooting_failed": True},
            {"current_intent": "general_query", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {}, "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-callback"
        _invoke_turn(graph, tid, "All machines are down")
        _invoke_turn(graph, tid, "No, still offline")
        r = _invoke_turn(graph, tid, "Please call me at 555-123-4567")
        t = _last_ai_text(r)
        self.assertIn("555-123-4567", t)
        self.assertNotIn("already been dispatched", t.lower())

    def test_post_escalation_human_request_no_phone(self) -> None:
        """After ticket dispatch, human request without phone prompts for callback number."""
        script = [
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": False, "troubleshooting_failed": False},
             "blast_radius": "entire_location", "troubleshooting_failed": False},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "entire_location", "troubleshooting_failed": True},
            {"current_intent": "escalation_request", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {}, "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-human-no-phone"
        _invoke_turn(graph, tid, "All machines are down")
        _invoke_turn(graph, tid, "No, still offline")
        r = _invoke_turn(graph, tid, "Please have someone contact me")
        t = _last_ai_text(r)
        self.assertIn("callback", t.lower())
        self.assertNotIn("already been dispatched", t.lower())

    def test_post_escalation_status_query(self) -> None:
        """After ticket dispatch, asking for status gets a status-specific response."""
        script = [
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": False, "troubleshooting_failed": False},
             "blast_radius": "entire_location", "troubleshooting_failed": False},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "entire_location", "troubleshooting_failed": True},
            {"current_intent": "general_query", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {}, "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-status-query"
        _invoke_turn(graph, tid, "All machines are down")
        _invoke_turn(graph, tid, "No, still offline")
        r = _invoke_turn(graph, tid, "Any update on the ticket status?")
        t = _last_ai_text(r)
        self.assertIn("dispatched", t.lower())
        self.assertNotIn("already been dispatched", t.lower())

    def test_post_escalation_additional_detail(self) -> None:
        """After ticket dispatch, providing extra detail gets a 'noted' response."""
        script = [
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": False, "troubleshooting_failed": False},
             "blast_radius": "entire_location", "troubleshooting_failed": False},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "entire_location", "troubleshooting_failed": True},
            {"current_intent": "general_query", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {}, "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-extra-detail"
        _invoke_turn(graph, tid, "All machines are down")
        _invoke_turn(graph, tid, "No, still offline")
        r = _invoke_turn(graph, tid, "Also machine 3 has the exact same problem since yesterday")
        t = _last_ai_text(r)
        self.assertIn("noted", t.lower())
        self.assertNotIn("already been dispatched", t.lower())

    def test_post_escalation_howto_goes_to_rag(self) -> None:
        """After ticket dispatch, a how-to question gets a RAG answer, not ticket notes."""
        script = [
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": False, "troubleshooting_failed": False},
             "blast_radius": "entire_location", "troubleshooting_failed": False},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "entire_location", "troubleshooting_failed": True},
            {"current_intent": "general_query", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {}, "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(
            script,
            rag_answer="Machines are managed in the Operator Portal under the Machines tab.",
        )
        tid = "test-howto-after-esc"
        _invoke_turn(graph, tid, "All machines are down")
        _invoke_turn(graph, tid, "No, still offline")
        r = _invoke_turn(graph, tid, "How do I add or edit machines?")
        t = _last_ai_text(r)
        self.assertIn("operator portal", t.lower())
        self.assertNotIn("noted", t.lower())
        self.assertNotIn("additional context", t.lower())

    def test_is_howto_or_info_query(self) -> None:
        """How-to detection covers portal questions but not ticket detail dumps."""
        from src.agent.graph import _is_howto_or_info_query
        self.assertTrue(_is_howto_or_info_query("How do I add or edit machines?"))
        self.assertTrue(_is_howto_or_info_query("Where do I manage machine information?"))
        self.assertTrue(_is_howto_or_info_query("What does network error mean"))
        self.assertFalse(_is_howto_or_info_query(
            "Also machine 3 has the exact same problem since yesterday"
        ))

    # --- Dedup tests ---

    def test_dedup_same_outage(self) -> None:
        """Rewording the same outage after ticket dispatch does NOT create a second ticket."""
        script = [
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": False, "troubleshooting_failed": False},
             "blast_radius": "entire_location", "troubleshooting_failed": False},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "entire_location", "troubleshooting_failed": True},
            {"current_intent": "emergency_store_down", "hardware_lookup_attempted": False,
             "escalation_required": True, "api_action_required": False,
             "extracted_entities": {"blast_radius": "entire_location"},
             "blast_radius": "entire_location", "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-dedup-same"
        _invoke_turn(graph, tid, "All machines are down")
        _invoke_turn(graph, tid, "No, still offline")
        self.assertEqual(self._mock_send_escalation.call_count, 1)
        r = _invoke_turn(graph, tid, "Nothing is working, all machines are still down")
        self.assertEqual(self._mock_send_escalation.call_count, 1)

    def test_dedup_different_issue(self) -> None:
        """A genuinely different issue after ticket dispatch DOES create a new ticket."""
        script = [
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine"},
             "blast_radius": "single_machine", "troubleshooting_failed": False},
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "single_machine", "troubleshooting_failed": True},
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "single_machine", "troubleshooting_failed": True},
            {"current_intent": "kiosk_not_responding", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {},
             "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-dedup-diff"
        _invoke_turn(graph, tid, "Machine 5 is down")
        _invoke_turn(graph, tid, "No, still broken")
        _invoke_turn(graph, tid, "yes please escalate")
        self.assertEqual(self._mock_send_escalation.call_count, 1)
        r = _invoke_turn(graph, tid, "Also the kiosk touchscreen is completely frozen and unresponsive")
        t = _last_ai_text(r)
        self.assertIn("did this resolve", t.lower())


class EscalationGateTests(unittest.TestCase):
    """Tests for the sticky-gate fix: substantive queries escape the confirm prompt."""

    def _build_graph(self, router_script, rag_answer=None):
        from unittest.mock import MagicMock
        self._router_iter = iter(router_script)

        def _mock_router(_state):
            return next(self._router_iter)

        mock_rag = MagicMock()
        mock_rag.query.return_value = {
            "answer": rag_answer or "You can assign a static IP via the hub settings page.",
            "context": [],
        }
        self._nodes_rag_patcher = patch(
            "src.agent.nodes.get_rag_service",
            return_value=mock_rag,
        )
        self._nodes_rag_patcher.start()

        self._router_patcher = patch("src.agent.graph.semantic_router", side_effect=_mock_router)
        self._router_patcher.start()

        self._escalation_patcher = patch.object(
            NotificationService,
            "send_escalation",
            return_value=EscalationResult(email_sent=True, sms_sent=True),
        )
        self._escalation_patcher.start()

        return create_agent_graph()

    def tearDown(self) -> None:
        for p in ("_nodes_rag_patcher", "_router_patcher", "_escalation_patcher"):
            patcher = getattr(self, p, None)
            if patcher:
                patcher.stop()

    def test_substantive_query_escapes_gate(self) -> None:
        """After 'Would you like to escalate?', a new 4+ word query gets a RAG answer."""
        script = [
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine"},
             "blast_radius": "single_machine", "troubleshooting_failed": False},
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "single_machine", "troubleshooting_failed": True},
            {"current_intent": "technical_support", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {},
             "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script, rag_answer="You can assign a static IP via the hub settings page.")
        tid = "test-gate-escape"
        _invoke_turn(graph, tid, "Machine 5 is down")
        _invoke_turn(graph, tid, "No, still broken")
        r = _invoke_turn(graph, tid, "Can I assign a static IP to the hub?")
        t = _last_ai_text(r)
        self.assertNotIn("would you like me to escalate", t.lower())
        self.assertIn("static ip", t.lower())

    def test_short_garbage_reasks(self) -> None:
        """After 'Would you like to escalate?', short garbage re-asks."""
        script = [
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine"},
             "blast_radius": "single_machine", "troubleshooting_failed": False},
            {"current_intent": "machine_down", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {"blast_radius": "single_machine", "troubleshooting_done": True, "troubleshooting_failed": True},
             "blast_radius": "single_machine", "troubleshooting_failed": True},
            {"current_intent": "out_of_domain", "hardware_lookup_attempted": False,
             "escalation_required": False, "api_action_required": False,
             "extracted_entities": {},
             "blast_radius": None, "troubleshooting_failed": None},
        ]
        graph = self._build_graph(script)
        tid = "test-gate-reask"
        _invoke_turn(graph, tid, "Machine 5 is down")
        _invoke_turn(graph, tid, "No, still broken")
        r = _invoke_turn(graph, tid, "asdf")
        t = _last_ai_text(r)
        self.assertIn("would you like me to escalate", t.lower())


class FollowUpQueryExpansionTests(unittest.TestCase):
    """Tests for RAG follow-up context expansion when user sends short affirmatives."""

    def test_short_followup_with_article_id(self) -> None:
        """'yes provide me' after AI mentioning KB-READER-008 expands query + sets article filter."""
        from src.agent.nodes import _expand_followup_query, _is_short_followup
        from langchain_core.messages import AIMessage as AI, HumanMessage as HM
        msgs = [
            AI(content='Network Error means the Hub did not complete the internet path. Refer to KB-READER-008 for resolution.'),
            HM(content="yes provide me"),
        ]
        self.assertTrue(_is_short_followup("yes provide me"))
        query, filt = _expand_followup_query(msgs)
        self.assertIsNotNone(filt)
        self.assertEqual(filt, {"article_id": {"$eq": "KB-READER-008"}})
        self.assertIn("yes provide me", query)

    def test_short_followup_topic_prepend(self) -> None:
        """'tell me more' after AI with no article ID prepends first sentence."""
        from src.agent.nodes import _expand_followup_query
        from langchain_core.messages import AIMessage as AI, HumanMessage as HM
        msgs = [
            AI(content="The cashbox stores coins and bills. You should clear it weekly."),
            HM(content="tell me more"),
        ]
        query, filt = _expand_followup_query(msgs)
        self.assertIsNone(filt)
        self.assertIn("cashbox stores coins and bills", query)
        self.assertIn("tell me more", query)

    def test_long_message_not_expanded(self) -> None:
        """A substantive 7+ word query should NOT be treated as a follow-up."""
        from src.agent.nodes import _expand_followup_query, _is_short_followup
        from langchain_core.messages import AIMessage as AI, HumanMessage as HM
        msgs = [
            AI(content="Refer to KB-READER-008 for network error steps."),
            HM(content="How do I reset the hub to factory defaults?"),
        ]
        self.assertFalse(_is_short_followup("How do I reset the hub to factory defaults?"))
        query, filt = _expand_followup_query(msgs)
        self.assertIsNone(filt)
        self.assertEqual(query, "How do I reset the hub to factory defaults?")

    def test_did_this_resolve_guard(self) -> None:
        """Follow-up after 'Did this resolve?' should NOT expand (handled by route_after_rag)."""
        from src.agent.nodes import _expand_followup_query
        from langchain_core.messages import AIMessage as AI, HumanMessage as HM
        msgs = [
            AI(content="Power-cycle the hub.\n\nDid this resolve the issue? (Yes/No)"),
            HM(content="yes"),
        ]
        query, filt = _expand_followup_query(msgs)
        self.assertEqual(query, "yes")
        self.assertIsNone(filt)

    def test_multiple_article_ids_uses_last(self) -> None:
        """When prior AI mentions multiple articles, the last one is used."""
        from src.agent.nodes import _expand_followup_query
        from langchain_core.messages import AIMessage as AI, HumanMessage as HM
        msgs = [
            AI(content="See KB-FAQ-009 for the meaning. For troubleshooting steps, refer to KB-READER-008."),
            HM(content="yes please"),
        ]
        _, filt = _expand_followup_query(msgs)
        self.assertEqual(filt, {"article_id": {"$eq": "KB-READER-008"}})

    def test_is_short_followup_variants(self) -> None:
        """Various short follow-up phrases are detected correctly."""
        from src.agent.nodes import _is_short_followup
        positives = ["yes", "yes please", "show me", "give me the steps", "go ahead", "please provide", "ok"]
        for phrase in positives:
            self.assertTrue(_is_short_followup(phrase), f"Expected True for: {phrase!r}")
        negatives = ["How do I reset the hub?", "My machine is showing error code E5", ""]
        for phrase in negatives:
            self.assertFalse(_is_short_followup(phrase), f"Expected False for: {phrase!r}")


class BlastRadiusDedupTests(unittest.TestCase):
    """Tests for blast-radius-aware duplicate outage detection."""

    def test_same_blast_radius_is_duplicate(self) -> None:
        """Same blast radius + high word overlap = duplicate."""
        from src.agent.graph import _is_duplicate_outage
        state = {
            "extracted_entities": {
                "last_ticket_summary": "all machines are down",
                "last_ticket_blast_radius": "entire_location",
                "blast_radius": "entire_location",
            },
            "blast_radius": "entire_location",
            "last_ticket_blast_radius": "entire_location",
        }
        self.assertTrue(_is_duplicate_outage(state, "all machines are still down"))

    def test_different_blast_radius_not_duplicate(self) -> None:
        """Different blast radius = NOT duplicate, even with high word overlap."""
        from src.agent.graph import _is_duplicate_outage
        state = {
            "extracted_entities": {
                "last_ticket_summary": "all machine is down",
                "last_ticket_blast_radius": "entire_location",
                "blast_radius": "single_machine",
            },
            "blast_radius": "single_machine",
            "last_ticket_blast_radius": "entire_location",
        }
        self.assertFalse(_is_duplicate_outage(state, "one machine is down"))

    def test_no_blast_radius_falls_back_to_jaccard(self) -> None:
        """When blast radius is missing, Jaccard still works as before."""
        from src.agent.graph import _is_duplicate_outage
        state = {
            "extracted_entities": {
                "last_ticket_summary": "kiosk touchscreen frozen",
            },
        }
        self.assertTrue(_is_duplicate_outage(state, "kiosk touchscreen is frozen"))
        self.assertFalse(_is_duplicate_outage(state, "card reader shows network error"))


class GreetingResetTests(unittest.TestCase):
    """Tests that greeting node clears escalation routing flags."""

    def test_greeting_clears_escalation_state(self) -> None:
        """handle_greeting returns state that clears escalation_dispatched and workflow flags."""
        from src.agent.nodes import handle_greeting
        state = {
            "messages": [HumanMessage(content="hi")],
            "escalation_dispatched": True,
            "blast_radius": "entire_location",
            "troubleshooting_failed": True,
            "extracted_entities": {
                "troubleshooting_done": True,
                "blast_radius_asked": True,
                "escalation_confirmation_asked": True,
            },
        }
        result = handle_greeting(state)
        self.assertIsNone(result.get("escalation_dispatched"))
        self.assertIsNone(result.get("blast_radius"))
        self.assertIsNone(result.get("troubleshooting_failed"))
        ents = result.get("extracted_entities", {})
        self.assertFalse(ents.get("troubleshooting_done"))
        self.assertFalse(ents.get("blast_radius_asked"))
        self.assertFalse(ents.get("escalation_confirmation_asked"))
        self.assertIn("hello", _last_ai_text(result).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
