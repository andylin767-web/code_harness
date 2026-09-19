import unittest

from code_harness.goals.command import GoalCommandHandler
from code_harness.goals.models import GoalLifecycle, GoalState


class FakeGoalController:
    def __init__(self):
        self.status = None
        self.active = None
        self.set_calls = []
        self.clear_calls = []

    def set_goal(self, condition, conversation_id, tokens_at_start=0):
        if condition == "invalid":
            raise ValueError("invalid goal")
        self.set_calls.append((condition, conversation_id, tokens_at_start))
        self.active = GoalState(
            id="goal_123",
            conversation_id=conversation_id,
            condition=condition,
            tokens_at_start=tokens_at_start,
        )
        return self.active

    def inspect(self, current_tokens=0):
        return self.status

    def clear(self, reason="cleared by user"):
        self.clear_calls.append(reason)
        active = self.active
        self.active = None
        if active is not None:
            active.lifecycle = GoalLifecycle.CLEARED
        return active


class GoalCommandHandlerTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeGoalController()
        self.handler = GoalCommandHandler(self.controller)

    def test_non_goal_input_is_not_handled(self):
        result = self.handler.handle(
            "please edit the file",
            conversation_id="conv_123",
        )

        self.assertFalse(result.handled)
        self.assertFalse(result.starts_work)

    def test_similar_command_name_is_not_handled(self):
        result = self.handler.handle(
            "/goalkeeper status",
            conversation_id="conv_123",
        )

        self.assertFalse(result.handled)

    def test_bare_goal_command_displays_status(self):
        self.controller.status = {
            "condition": "pytest exits with code 0",
            "lifecycle": "active",
            "evaluation_count": 2,
            "consecutive_blocks": 1,
            "tokens_used": 250,
            "elapsed_seconds": 4.25,
            "latest_reason": "Need another test run.",
        }

        result = self.handler.handle(
            "/goal",
            conversation_id="conv_123",
            current_tokens=500,
        )

        self.assertTrue(result.handled)
        self.assertIn("Status: active", result.output)
        self.assertIn("Evaluations: 2", result.output)
        self.assertIn("Elapsed: 4.2s", result.output)
        self.assertIn("Need another test run.", result.output)

    def test_status_alias_displays_empty_status(self):
        result = self.handler.handle(
            "/goal\tstatus",
            conversation_id="conv_123",
        )

        self.assertEqual(result.output, "No goal has been set.")

    def test_condition_sets_goal_and_returns_work_request(self):
        result = self.handler.handle(
            "/goal   Pytest tests/auth exits with code 0  ",
            conversation_id="conv_123",
            current_tokens=125,
        )

        self.assertTrue(result.handled)
        self.assertTrue(result.starts_work)
        self.assertEqual(
            result.work_request,
            "Pytest tests/auth exits with code 0",
        )
        self.assertEqual(
            self.controller.set_calls,
            [("Pytest tests/auth exits with code 0", "conv_123", 125)],
        )

    def test_clear_aliases_clear_without_starting_work(self):
        for alias in ("clear", "stop", "off", "reset", "none", "cancel"):
            with self.subTest(alias=alias):
                self.controller.active = GoalState(
                    id="goal_123",
                    conversation_id="conv_123",
                    condition="condition",
                )

                result = self.handler.handle(
                    f"/goal {alias}",
                    conversation_id="conv_123",
                )

                self.assertTrue(result.handled)
                self.assertFalse(result.starts_work)
                self.assertIn("Cleared goal", result.output)

    def test_clear_reports_when_no_goal_is_active(self):
        result = self.handler.handle(
            "/goal clear",
            conversation_id="conv_123",
        )

        self.assertEqual(result.output, "No active goal to clear.")

    def test_help_lists_supported_operations(self):
        result = self.handler.handle(
            "/goal help",
            conversation_id="conv_123",
        )

        self.assertIn("/goal <condition>", result.output)
        self.assertIn("Clear aliases", result.output)

    def test_controller_validation_error_is_returned_to_user(self):
        result = self.handler.handle(
            "/goal invalid",
            conversation_id="conv_123",
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.error, "invalid goal")
        self.assertIn("Could not set goal", result.output)


if __name__ == "__main__":
    unittest.main()
