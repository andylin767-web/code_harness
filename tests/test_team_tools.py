import unittest
from unittest.mock import Mock

from code_harness.team.message_type import MessageType
from code_harness.team.protocol_state import ProtocolType
from code_harness.team.send import Sender
from code_harness.tools.team import (
    SendMessageInput,
    SendMessageTool,
    TeammateSendMessageInput,
    TeammateSendMessageTool,
)


class TeamMessageToolTests(unittest.TestCase):
    def test_lead_message_uses_sender(self):
        sender = Mock(spec=Sender)
        sender.send_from_lead.return_value = "Sent message to reviewer"
        tool = SendMessageTool(sender)

        result = tool.run(
            SendMessageInput(to="reviewer", content="Please review this")
        )

        sender.send_from_lead.assert_called_once_with(
            to="reviewer",
            content="Please review this",
            msg_type=MessageType.MESSAGE,
        )
        self.assertEqual(result, "Sent message to reviewer")

    def test_teammate_message_forwards_type_and_metadata(self):
        sender = Mock(spec=Sender)
        sender.send_from_teammate.return_value = "Sent message to lead"
        tool = TeammateSendMessageTool(sender)

        result = tool.run(
            TeammateSendMessageInput(
                name="reviewer",
                to="lead",
                content="Implementation plan",
                msg_type=ProtocolType.PLAN_APPROVAL_REQUEST,
                metadata={"request_id": "req_plan"},
            )
        )

        sender.send_from_teammate.assert_called_once_with(
            name="reviewer",
            to="lead",
            content="Implementation plan",
            msg_type=ProtocolType.PLAN_APPROVAL_REQUEST,
            metadata={"request_id": "req_plan"},
        )
        self.assertEqual(result, "Sent message to lead")


if __name__ == "__main__":
    unittest.main()
