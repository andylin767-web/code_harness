import json
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("litellm", types.ModuleType("litellm"))

from code_harness.core import tracing
from code_harness.core.loop import Loop, LoopStatus
from code_harness.core.permissions import PermissionDecision
from code_harness.goals.models import GoalState, StopAction, StopDecision
from code_harness.memory.context import ConversationStore, MessageType


class FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": self.tool_calls,
        }


class FakeLLMClient:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.call_count = 0

    async def send(self, *args, **kwargs):
        self.call_count += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=next(self.messages))])


class FakeToolRegistry:
    def get(self, name):
        return None

    def schemas(self):
        return []


class FakeAgent:
    def __init__(self, workspace_root):
        self.model = "test-model"
        self.workspace_root = Path(workspace_root)
        self.toolset = FakeToolRegistry()

    def build_system_prompt(self):
        return "test system prompt"


class FakePermissionEngine:
    def set_workspace_root(self, workspace_root):
        self.workspace_root = workspace_root

    async def decide_bash_with_llm_fallback(self, command):
        return PermissionDecision.ALLOW


class FakeGoalController:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.calls = []

    async def evaluate_after_turn(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.decisions)


class LoopRefactorTests(unittest.IsolatedAsyncioTestCase):
    def make_loop(self, workspace_root, goal_controller=None):
        with patch("builtins.print"):
            return Loop(
                FakeAgent(workspace_root),
                FakePermissionEngine(),
                goal_controller=goal_controller,
            )

    async def test_run_returns_worker_response_without_active_goal(self):
        with TemporaryDirectory() as tmpdir:
            loop = self.make_loop(tmpdir)
            store = ConversationStore()
            llm_client = FakeLLMClient([FakeMessage("finished")])

            with patch("code_harness.core.loop.LLMClient", return_value=llm_client):
                result = await loop.run(store, "conv_123", "do the work")

            self.assertIs(result.status, LoopStatus.COMPLETED)
            self.assertEqual(result.summary, "finished")
            self.assertEqual(result.runs, 0)
            self.assertEqual(result.tool_calls, 0)

    async def test_goal_block_adds_feedback_and_runs_another_turn(self):
        controller = FakeGoalController(
            [
                StopDecision(StopAction.BLOCK, "Run pytest."),
                StopDecision(StopAction.ALLOW, "Tests passed."),
            ]
        )
        with TemporaryDirectory() as tmpdir:
            loop = self.make_loop(tmpdir, controller)
            store = ConversationStore()
            llm_client = FakeLLMClient(
                [FakeMessage("not done"), FakeMessage("now finished")]
            )

            with patch("code_harness.core.loop.LLMClient", return_value=llm_client):
                result = await loop.run(store, "conv_123", "complete the goal")

            feedback = [
                record
                for record in store.records
                if record.type is MessageType.USER
                and isinstance(record.content, str)
                and record.content.startswith("<goal_feedback>")
            ]
            self.assertEqual(len(feedback), 1)
            self.assertIn("Run pytest.", feedback[0].content)
            self.assertEqual(len(controller.calls), 2)
            self.assertIs(result.status, LoopStatus.COMPLETED)
            self.assertEqual(result.summary, "now finished")
            self.assertEqual(result.runs, 1)

    async def test_unknown_tool_is_recorded_and_counted(self):
        tool_call = SimpleNamespace(
            id="call_123",
            function=SimpleNamespace(name="missing_tool", arguments="{}"),
        )
        with TemporaryDirectory() as tmpdir:
            loop = self.make_loop(tmpdir)
            store = ConversationStore()
            llm_client = FakeLLMClient(
                [
                    FakeMessage(None, [tool_call]),
                    FakeMessage("finished"),
                ]
            )

            with patch("code_harness.core.loop.LLMClient", return_value=llm_client):
                result = await loop.run(store, "conv_123", "do the work")

            tool_records = [
                record for record in store.records if record.type is MessageType.TOOL
            ]
            self.assertEqual(len(tool_records), 1)
            self.assertIn("Unknown tool: missing_tool", str(tool_records[0].content))
            self.assertEqual(result.tool_calls, 1)
            self.assertEqual(result.runs, 1)

    async def test_background_tool_immediately_defers_without_another_llm_call(self):
        background_call = SimpleNamespace(
            id="call_background",
            function=SimpleNamespace(
                name="bash",
                arguments='{"command": "python -m pytest"}',
            ),
        )
        later_call = SimpleNamespace(
            id="call_later",
            function=SimpleNamespace(name="read_file", arguments="{}"),
        )

        class ToolRegistry(FakeToolRegistry):
            def get(self, name):
                return object()

        class BackgroundRunner:
            def collect_completed(self):
                return []

            def should_run_tool_call(self, tool_call):
                return tool_call.id == "call_background"

            def start(self, tool_call):
                return "bg_0001"

        with TemporaryDirectory() as tmpdir:
            controller = FakeGoalController([])
            controller.active = GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="pytest exits with code 0",
            )
            loop = self.make_loop(tmpdir, controller)
            loop.agent.toolset = ToolRegistry()
            loop._create_background_runner = lambda *args: BackgroundRunner()
            store = ConversationStore()
            llm_client = FakeLLMClient(
                [FakeMessage(None, [background_call, later_call])]
            )

            with (
                patch("code_harness.core.loop.LLMClient", return_value=llm_client),
                patch.object(tracing, "TRACE_DIR", Path(tmpdir)),
            ):
                result = await loop.run(
                    store,
                    "conv_123",
                    "run the tests",
                    event_id="event_123",
                    event_type="user",
                    run_id="run_123",
                )

            tool_records = [
                record for record in store.records if record.type is MessageType.TOOL
            ]
            self.assertIs(result.status, LoopStatus.GOAL_DEFERRED)
            self.assertEqual(
                result.summary, "Background task bg_0001 is still running."
            )
            self.assertEqual(result.tool_calls, 1)
            self.assertEqual(llm_client.call_count, 1)
            self.assertEqual(len(tool_records), 2)
            self.assertIn(
                "Started background task bg_0001", str(tool_records[0].content)
            )
            self.assertIn(
                "Skipped because background task bg_0001", str(tool_records[1].content)
            )
            goal_events = [
                json.loads(line)
                for line in (Path(tmpdir) / "goals" / "goal_123.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [event["stage"] for event in goal_events],
                ["worker_started", "permission_decided", "worker_deferred"],
            )
            self.assertTrue(
                all(event["event_id"] == "event_123" for event in goal_events)
            )
            self.assertEqual(
                goal_events[-1]["background_task_id"],
                "bg_0001",
            )


if __name__ == "__main__":
    unittest.main()
