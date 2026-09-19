import unittest
from types import SimpleNamespace

from code_harness.goals.evaluator import (
    GoalEvaluationError,
    PromptGoalEvaluator,
)
from code_harness.goals.models import GoalState


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
        )


class GoalEvaluatorParsingTests(unittest.TestCase):
    def test_parses_plain_json(self):
        payload = PromptGoalEvaluator._parse_payload(
            '{"ok": true, "reason": "Tests passed", "impossible": false}'
        )

        self.assertTrue(payload.ok)
        self.assertEqual(payload.reason, "Tests passed")

    def test_parses_markdown_fenced_json(self):
        payload = PromptGoalEvaluator._parse_payload(
            "```json\n"
            '{"ok": false, "reason": "Missing test output", '
            '"impossible": false}\n'
            "```"
        )

        self.assertFalse(payload.ok)
        self.assertEqual(payload.reason, "Missing test output")

    def test_parses_json_after_reasoning_prefix(self):
        payload = PromptGoalEvaluator._parse_payload(
            "I will compare the condition with the evidence.\n"
            "<analysis>The command output proves success.</analysis>\n"
            '{"ok": true, "reason": "Exit code was 0", '
            '"impossible": false}'
        )

        self.assertTrue(payload.ok)
        self.assertEqual(payload.reason, "Exit code was 0")

    def test_rejects_embedded_json_with_wrong_schema(self):
        with self.assertRaisesRegex(
            GoalEvaluationError,
            "Invalid goal evaluator response",
        ):
            PromptGoalEvaluator._parse_payload('Analysis metadata: {"answer": true}')


class PromptGoalEvaluatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_json_object_response_format(self):
        client = FakeClient(
            '{"ok": true, "reason": "Tests passed", "impossible": false}'
        )
        evaluator = PromptGoalEvaluator(client=client, model="test-model")
        goal = GoalState(
            id="goal_123",
            conversation_id="conv_123",
            condition="pytest exits with code 0",
        )

        result = await evaluator.evaluate(goal, [])

        self.assertTrue(result.ok)
        self.assertEqual(
            client.calls[0]["response_format"],
            {"type": "json_object"},
        )


if __name__ == "__main__":
    unittest.main()
