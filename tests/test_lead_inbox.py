import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from code_harness.events.runtime import set_event_queue
from code_harness.team.lead_inbox import (
    LeadInbox,
    consume_lead_inbox,
    set_lead_inbox,
)
from code_harness.team.message_bus import MessageBus
from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_runtime import set_protocol_manager
from code_harness.team.protocol_state import ProtocolStatus, ProtocolType
from code_harness.team.send import Sender
from code_harness.tools.team import CheckInBoxInput, CheckInboxTool


class LeadInboxTests(unittest.TestCase):
    def tearDown(self):
        set_event_queue(None)
        set_lead_inbox(None)
        set_protocol_manager(None)

    def test_consume_routes_protocol_response_before_returning_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir) / "mailboxes")
            manager = ProtocolManager()
            set_protocol_manager(manager)
            set_lead_inbox(LeadInbox(bus))
            request = manager.create_request(
                type=ProtocolType.SHUTDOWN_REQUEST,
                sender="lead",
                target="reviewer",
                payload="Work complete",
            )
            bus.send(
                from_agent="reviewer",
                to_agent="lead",
                content="Shutting down",
                msg_type=ProtocolType.SHUTDOWN_RESPONSE,
                metadata={
                    "request_id": request.request_id,
                    "approve": True,
                },
            )

            messages = consume_lead_inbox()

            self.assertEqual(len(messages), 1)
            self.assertIs(request.status, ProtocolStatus.APPROVED)
            self.assertEqual(consume_lead_inbox(), [])

    def test_route_protocol_false_returns_without_resolving(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir) / "mailboxes")
            manager = ProtocolManager()
            set_protocol_manager(manager)
            set_lead_inbox(LeadInbox(bus))
            request = manager.create_request(
                type=ProtocolType.SHUTDOWN_REQUEST,
                sender="lead",
                target="reviewer",
                payload="Work complete",
            )
            bus.send(
                from_agent="reviewer",
                to_agent="lead",
                content="No",
                msg_type=ProtocolType.SHUTDOWN_RESPONSE,
                metadata={
                    "request_id": request.request_id,
                    "approve": False,
                },
            )

            messages = consume_lead_inbox(route_protocol=False)

            self.assertEqual(len(messages), 1)
            self.assertIs(request.status, ProtocolStatus.PENDING)

    def test_check_inbox_consumes_lead_through_shared_function(self):
        sender = Mock(spec=Sender)
        tool = CheckInboxTool(sender)
        expected = [{"from": "reviewer", "content": "Done"}]

        with patch(
            "code_harness.tools.team.consume_lead_inbox",
            return_value=expected,
        ) as consume:
            result = tool.run(CheckInBoxInput(agent="lead"))

        consume.assert_called_once_with()
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
