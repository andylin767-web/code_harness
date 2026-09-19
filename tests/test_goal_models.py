import unittest
from datetime import UTC, datetime

from code_harness.goals.models import (
    GoalEvaluation,
    GoalLifecycle,
    GoalState,
    StopAction,
    StopDecision,
)


class GoalModelTests(unittest.TestCase):
    def test_goal_state_defaults_to_active_with_aware_timestamps(self):
        goal = GoalState(
            id="goal_123",
            conversation_id="conv_123",
            condition="pytest exits with code 0",
        )

        self.assertIs(goal.lifecycle, GoalLifecycle.ACTIVE)
        self.assertTrue(goal.is_active)
        self.assertEqual(goal.evaluation_count, 0)
        self.assertEqual(goal.consecutive_blocks, 0)
        self.assertEqual(goal.tokens_at_start, 0)
        self.assertIsNotNone(goal.created_at.tzinfo)
        self.assertIsNotNone(goal.updated_at.tzinfo)

    def test_terminal_lifecycle_is_not_active(self):
        goal = GoalState(
            id="goal_123",
            conversation_id="conv_123",
            condition="pytest exits with code 0",
            lifecycle=GoalLifecycle.COMPLETED,
            completed_at=datetime.now(UTC),
        )

        self.assertFalse(goal.is_active)
        self.assertTrue(goal.lifecycle.is_terminal)
        self.assertFalse(GoalLifecycle.ACTIVE.is_terminal)

    def test_stop_decision_uses_typed_action(self):
        decision = StopDecision(
            action=StopAction.BLOCK,
            reason="The test exit code is missing.",
        )

        self.assertIs(decision.action, StopAction.BLOCK)

    def test_evaluation_cannot_be_satisfied_and_impossible(self):
        with self.assertRaisesRegex(ValueError, "both satisfied and impossible"):
            GoalEvaluation(ok=True, reason="conflicting result", impossible=True)

    def test_goal_rejects_empty_condition(self):
        with self.assertRaisesRegex(ValueError, "condition cannot be empty"):
            GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="   ",
            )

    def test_goal_rejects_naive_timestamps(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="pytest exits with code 0",
                created_at=datetime.now(),
            )


if __name__ == "__main__":
    unittest.main()
