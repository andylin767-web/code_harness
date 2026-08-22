import unittest
from unittest.mock import Mock

from code_harness.team.message_type import MessageType
from code_harness.team.protocol_dispatcher import ProtocolDispatcher
from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_state import ProtocolStatus, ProtocolType
from code_harness.team.send import Sender


class ProtocolDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.sender = Mock(spec=Sender)
        self.manager = ProtocolManager()
        self.dispatcher = ProtocolDispatcher(self.sender, self.manager)

    def test_shutdown_request_sends_typed_teammate_response(self):
        messages = []

        should_stop = self.dispatcher.dispatch(
            "reviewer",
            {
                "type": ProtocolType.SHUTDOWN_REQUEST,
                "metadata": {"request_id": "req_shutdown"},
            },
            messages,
        )

        self.assertTrue(should_stop)
        self.assertEqual(messages, [])
        self.sender.send_from_teammate.assert_called_once_with(
            name="reviewer",
            to="lead",
            content="Shutting down gracefully.",
            msg_type=ProtocolType.SHUTDOWN_RESPONSE,
            metadata={
                "request_id": "req_shutdown",
                "approve": True,
            },
        )

    def test_plan_response_updates_teammate_conversation(self):
        messages = []

        should_stop = self.dispatcher.dispatch(
            "reviewer",
            {
                "type": ProtocolType.PLAN_APPROVAL_RESPONSE,
                "content": "Add rollback steps.",
                "metadata": {"approve": False},
            },
            messages,
        )

        self.assertFalse(should_stop)
        self.assertEqual(
            messages[0]["content"],
            "[Plan rejected] Feedback: Add rollback steps.",
        )

    def test_shutdown_response_resolves_lead_request(self):
        request = self.manager.create_request(
            type=ProtocolType.SHUTDOWN_REQUEST,
            sender="lead",
            target="reviewer",
            payload="Work complete",
        )

        should_stop = self.dispatcher.dispatch_to_lead(
            {
                "type": ProtocolType.SHUTDOWN_RESPONSE,
                "metadata": {
                    "request_id": request.request_id,
                    "approve": True,
                },
            },
            [],
        )

        self.assertFalse(should_stop)
        self.assertIs(request.status, ProtocolStatus.APPROVED)

    def test_shutdown_response_without_request_id_reports_error(self):
        messages = []

        self.dispatcher.dispatch_to_lead(
            {
                "type": ProtocolType.SHUTDOWN_RESPONSE,
                "metadata": {},
            },
            messages,
        )

        self.assertIn("missing request_id", messages[0]["content"])

    def test_plan_request_is_registered_for_review(self):
        messages = []

        should_stop = self.dispatcher.dispatch_to_lead(
            {
                "from": "reviewer",
                "to": "lead",
                "type": ProtocolType.PLAN_APPROVAL_REQUEST,
                "content": "1. Implement\n2. Test",
                "metadata": {"request_id": "req_plan"},
            },
            messages,
        )

        request = self.manager.get_request("req_plan")
        self.assertFalse(should_stop)
        self.assertIsNotNone(request)
        self.assertIs(request.type, ProtocolType.PLAN_APPROVAL_REQUEST)
        self.assertEqual(request.sender, "reviewer")
        self.assertEqual(request.payload, "1. Implement\n2. Test")
        self.assertIn("Request ID: req_plan", messages[0]["content"])
        self.assertIn("Use review_plan", messages[0]["content"])

    def test_conflicting_plan_request_reports_protocol_error(self):
        self.manager.create_request(
            type=ProtocolType.SHUTDOWN_REQUEST,
            sender="lead",
            target="reviewer",
            payload="",
            request_id="req_conflict",
        )
        messages = []

        self.dispatcher.dispatch_to_lead(
            {
                "from": "reviewer",
                "type": ProtocolType.PLAN_APPROVAL_REQUEST,
                "content": "Plan",
                "metadata": {"request_id": "req_conflict"},
            },
            messages,
        )

        self.assertIn("not a plan request", messages[0]["content"])

    def test_duplicate_plan_request_rejects_changed_content(self):
        self.manager.create_request(
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender="reviewer",
            target="lead",
            payload="Original plan",
            request_id="req_plan",
        )
        messages = []

        self.dispatcher.dispatch_to_lead(
            {
                "from": "reviewer",
                "type": ProtocolType.PLAN_APPROVAL_REQUEST,
                "content": "Changed plan",
                "metadata": {"request_id": "req_plan"},
            },
            messages,
        )

        self.assertIn("conflicting plan content", messages[0]["content"])

    def test_unknown_message_type_uses_normal_handler(self):
        messages = []

        self.dispatcher.dispatch_to_lead(
            {
                "from": "reviewer",
                "type": MessageType.ERROR,
                "content": "Task failed",
            },
            messages,
        )

        self.assertIn("Type: error", messages[0]["content"])
        self.assertIn("Task failed", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
