import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_state import ProtocolStatus, ProtocolType
from code_harness.team.send import Sender
from code_harness.tools.team import ReviewPlanInput, ReviewPlanTool
from pydantic import ValidationError


class ReviewPlanInputTests(unittest.TestCase):
    def test_accepts_request_id_approval_and_feedback(self):
        review = ReviewPlanInput(
            request_id="req_plan",
            approve=True,
            feedback="The plan is ready to execute.",
        )

        self.assertEqual(review.request_id, "req_plan")
        self.assertTrue(review.approve)
        self.assertEqual(review.feedback, "The plan is ready to execute.")

    def test_requires_all_fields(self):
        with self.assertRaises(ValidationError):
            ReviewPlanInput()

    def test_tool_creates_its_own_dependencies(self):
        with (
            TemporaryDirectory() as tmpdir,
            patch(
                "code_harness.tools.team.PROJECT_ROOT",
                Path(tmpdir),
            ),
        ):
            tool = ReviewPlanTool()

        self.assertIsInstance(tool.sender, Sender)
        self.assertIsInstance(tool.protocol_manager, ProtocolManager)

    def test_tool_accepts_injected_dependencies(self):
        sender = Mock(spec=Sender)
        protocol_manager = ProtocolManager()

        tool = ReviewPlanTool(
            sender=sender,
            protocol_manager=protocol_manager,
        )

        self.assertIs(tool.sender, sender)
        self.assertIs(tool.protocol_manager, protocol_manager)

    def test_run_resolves_request_and_sends_typed_response(self):
        sender = Mock(spec=Sender)
        protocol_manager = ProtocolManager()
        request = protocol_manager.create_request(
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender="reviewer",
            target="lead",
            payload="Implementation plan",
        )
        tool = ReviewPlanTool(sender, protocol_manager)
        arguments = ReviewPlanInput(
            request_id=request.request_id,
            approve=True,
            feedback="Looks good.",
        )

        result = tool.run(arguments)

        self.assertIs(request.status, ProtocolStatus.APPROVED)
        sender.send_from_lead.assert_called_once_with(
            to="reviewer",
            content="Looks good.",
            msg_type=ProtocolType.PLAN_APPROVAL_RESPONSE,
            metadata={
                "request_id": request.request_id,
                "approve": True,
            },
        )
        self.assertEqual(result, f"Plan approved ({request.request_id})")

    def test_run_reports_unknown_request(self):
        tool = ReviewPlanTool(
            sender=Mock(spec=Sender),
            protocol_manager=ProtocolManager(),
        )

        result = tool.run(
            ReviewPlanInput(
                request_id="req_missing",
                approve=False,
                feedback="Needs revision.",
            )
        )

        self.assertEqual(result, "Request req_missing not found")


if __name__ == "__main__":
    unittest.main()
