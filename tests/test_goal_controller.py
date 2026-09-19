import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_harness.core import tracing
from code_harness.goals.context import GoalContextBuilder
from code_harness.goals.controller import GoalController
from code_harness.goals.models import GoalEvaluation, StopAction
from code_harness.memory.context import ConversationStore, MessageRecord


class SuccessfulEvaluator:
    model = "evaluator-model"

    async def evaluate(self, goal, messages):
        return GoalEvaluation(ok=True, reason="pytest exited with code 0")


class GoalControllerTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_goal_lifecycle_and_evaluation_stages_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(tracing, "TRACE_DIR", Path(tmpdir)):
                controller = GoalController(
                    evaluator=SuccessfulEvaluator(),
                    context_builder=GoalContextBuilder(),
                )
                goal = controller.set_goal(
                    "pytest exits with code 0",
                    "conv_123",
                )
                store = ConversationStore()
                store.append_record(
                    MessageRecord.tool(
                        conversation_id="conv_123",
                        content="Exit code: 0",
                        tool_call_id="call_123",
                    )
                )

                decision = await controller.evaluate_after_turn(
                    store=store,
                    conversation_id="conv_123",
                    event_id="event_123",
                    run_id="run_123",
                )

            lines = (
                (Path(tmpdir) / "goals" / f"{goal.id}.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            events = [json.loads(line) for line in lines]

            self.assertIs(decision.action, StopAction.ALLOW)
            self.assertEqual(
                [event["stage"] for event in events],
                [
                    "goal_set",
                    "evaluation_started",
                    "evaluation_completed",
                    "goal_completed",
                ],
            )
            self.assertEqual(events[1]["event_id"], "event_123")
            self.assertEqual(events[1]["run_id"], "run_123")
            self.assertEqual(
                events[1]["details"]["evaluator_model"],
                "evaluator-model",
            )
            self.assertEqual(events[2]["details"]["action"], "allow")


if __name__ == "__main__":
    unittest.main()
