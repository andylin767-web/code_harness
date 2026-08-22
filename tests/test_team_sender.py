import tempfile
import unittest
from pathlib import Path

from code_harness.team.message_bus import MessageBus
from code_harness.team.message_type import MessageType
from code_harness.team.protocol_state import ProtocolType
from code_harness.team.send import Sender


class SenderTests(unittest.TestCase):
    def test_peek_delegates_to_message_bus(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir))
            sender = Sender(bus)

            self.assertFalse(sender.peek("reviewer"))
            bus.send("lead", "reviewer", "Please review this")
            self.assertTrue(sender.peek("reviewer"))

    def test_send_from_lead_defaults_to_regular_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir))
            sender = Sender(bus)

            result = sender.send_from_lead("reviewer", "Please review this")
            messages = bus.read_inbox("reviewer")

        self.assertEqual(result, "Sent message to reviewer")
        self.assertEqual(messages[0]["type"], "message")
        self.assertEqual(messages[0]["metadata"], {})

    def test_send_from_lead_supports_protocol_type_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir))
            sender = Sender(bus)

            sender.send_from_lead(
                "reviewer",
                "Please shut down gracefully",
                msg_type=ProtocolType.SHUTDOWN_REQUEST,
                metadata={"request_id": "req_shutdown"},
            )
            messages = bus.read_inbox("reviewer")

        self.assertEqual(messages[0]["type"], "shutdown_request")
        self.assertEqual(
            messages[0]["metadata"],
            {"request_id": "req_shutdown"},
        )

    def test_send_from_teammate_supports_message_type_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir))
            sender = Sender(bus)

            result = sender.send_from_teammate(
                name="reviewer",
                to="coordinator",
                content="Review complete",
                msg_type=MessageType.RESULT,
                metadata={"task_id": "task_1"},
            )
            messages = bus.read_inbox("coordinator")

        self.assertEqual(result, "Sent message to coordinator")
        self.assertEqual(messages[0]["from"], "reviewer")
        self.assertEqual(messages[0]["type"], "result")
        self.assertEqual(messages[0]["metadata"], {"task_id": "task_1"})

    def test_teammate_sender_closure_forwards_protocol_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir))
            send = Sender(bus).make_teammate_sender("reviewer")

            send(
                "coordinator",
                "Plan ready",
                ProtocolType.PLAN_APPROVAL_REQUEST,
                {"request_id": "req_plan"},
            )
            messages = bus.read_inbox("coordinator")

        self.assertEqual(messages[0]["type"], "plan_approval_request")
        self.assertEqual(messages[0]["metadata"], {"request_id": "req_plan"})


if __name__ == "__main__":
    unittest.main()
