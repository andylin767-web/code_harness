import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_state import ProtocolStatus, ProtocolType
from code_harness.team.send import Sender
from code_harness.tools.team import SubmitPlanInput, SubmitPlanTool
from code_harness.tools.tools import get_tools


class SubmitPlanToolTests(unittest.TestCase):
    def test_input_requires_from_name_and_plan(self):
        with self.assertRaises(ValidationError):
            SubmitPlanInput()

    def test_creates_request_and_sends_plan_to_lead(self):
        sender = Mock(spec=Sender)
        protocol_manager = ProtocolManager()
        tool = SubmitPlanTool(sender, protocol_manager)

        result = tool.run(
            SubmitPlanInput(
                from_name="reviewer",
                plan="1. Implement the change\n2. Run tests",
            )
        )

        request = next(iter(protocol_manager.pending_requests.values()))
        self.assertIs(request.type, ProtocolType.PLAN_APPROVAL_REQUEST)
        self.assertIs(request.status, ProtocolStatus.PENDING)
        self.assertEqual(request.sender, "reviewer")
        self.assertEqual(request.target, "lead")
        self.assertEqual(
            request.payload,
            "1. Implement the change\n2. Run tests",
        )
        sender.send_from_teammate.assert_called_once_with(
            name="reviewer",
            to="lead",
            content="1. Implement the change\n2. Run tests",
            msg_type=ProtocolType.PLAN_APPROVAL_REQUEST,
            metadata={"request_id": request.request_id},
        )
        self.assertIn(request.request_id, result)

    def test_is_available_only_to_sub_agents(self):
        self.assertIsNotNone(get_tools("sub_agent").get("submit_plan"))
        self.assertIsNone(get_tools("parent").get("submit_plan"))


if __name__ == "__main__":
    unittest.main()
