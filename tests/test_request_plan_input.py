import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from pydantic import ValidationError

from code_harness.team.message_type import MessageType
from code_harness.team.send import Sender
from code_harness.tools.team import RequestPlanInput, RequestPlanTool


class RequestPlanInputTests(unittest.TestCase):
    def test_accepts_teammate_and_task(self):
        request = RequestPlanInput(
            teammate="reviewer",
            task="Plan the protocol integration",
        )

        self.assertEqual(request.teammate, "reviewer")
        self.assertEqual(request.task, "Plan the protocol integration")

    def test_requires_teammate_and_task(self):
        with self.assertRaises(ValidationError):
            RequestPlanInput()

    def test_tool_creates_its_own_sender(self):
        with TemporaryDirectory() as tmpdir:
            with patch(
                "code_harness.tools.team.PROJECT_ROOT",
                Path(tmpdir),
            ):
                tool = RequestPlanTool()

        self.assertIsInstance(tool.sender, Sender)

    def test_tool_sends_request_through_sender(self):
        sender = Mock(spec=Sender)
        tool = RequestPlanTool(sender=sender)

        result = tool.run(
            RequestPlanInput(
                teammate="reviewer",
                task="Plan the protocol integration",
            )
        )

        sender.send_from_lead.assert_called_once_with(
            to="reviewer",
            content=(
                "Please create a plan for this task: "
                "Plan the protocol integration"
            ),
            msg_type=MessageType.MESSAGE,
        )
        self.assertEqual(result, "Asked reviewer to submit a plan")


if __name__ == "__main__":
    unittest.main()
