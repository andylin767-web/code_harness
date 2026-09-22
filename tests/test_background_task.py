import asyncio
import time
import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from code_harness.core.background_task import BackgroundTaskRunner


@dataclass
class Block:
    id: str
    input: dict


class ToolLikeResult:
    def __init__(self, content: str):
        self.content = content


class BackgroundTaskRunnerTests(unittest.TestCase):
    def test_start_returns_stable_task_id_and_collects_output(self):
        runner = BackgroundTaskRunner(lambda block: ToolLikeResult("done"))

        task_id = runner.start(Block("call-1", {"command": "echo hi"}))

        self.assertEqual(task_id, "bg_0001")
        self.assertTrue(runner.has_pending())
        notifications = self._wait_for_notifications(runner)
        self.assertEqual(len(notifications), 1)
        self.assertIn("<task_id>bg_0001</task_id>", notifications[0])
        self.assertIn("<status>completed</status>", notifications[0])
        self.assertIn("<command>echo hi</command>", notifications[0])
        self.assertIn("<summary>done</summary>", notifications[0])
        self.assertFalse(runner.has_pending())
        self.assertEqual(runner.collect_completed(), [])

    def test_supports_async_executor(self):
        async def execute(block):
            await asyncio.sleep(0)
            return "async done"

        runner = BackgroundTaskRunner(execute)
        runner.start(Block("call-1", {"command": "pytest"}))

        notification = self._wait_for_notifications(runner)[0]
        self.assertIn("<status>completed</status>", notification)
        self.assertIn("<summary>async done</summary>", notification)

    def test_executor_exceptions_are_reported_as_failed(self):
        def execute(block):
            raise RuntimeError("boom")

        runner = BackgroundTaskRunner(execute)
        runner.start(Block("call-1", {"command": "make"}))

        notification = self._wait_for_notifications(runner)[0]
        self.assertIn("<status>failed</status>", notification)
        self.assertIn("<summary>RuntimeError: boom</summary>", notification)

    def test_long_output_preserves_beginning_and_end(self):
        output = "BEGIN-EVIDENCE-" + ("x" * 1_000) + "-END-EVIDENCE"
        runner = BackgroundTaskRunner(lambda block: ToolLikeResult(output))

        runner.start(Block("call-1", {"command": "pytest"}))
        notification = self._wait_for_notifications(runner)[0]

        self.assertIn("BEGIN-EVIDENCE", notification)
        self.assertIn("END-EVIDENCE", notification)
        self.assertIn("truncated background output", notification)

    def test_should_run_background_uses_flag_and_slow_command_heuristic(self):
        runner = BackgroundTaskRunner(lambda block: "unused")

        self.assertTrue(
            runner.should_run_background("read_file", {"run_in_background": True})
        )
        self.assertTrue(runner.should_run_background("bash", {"command": "pytest"}))
        self.assertFalse(runner.should_run_background("bash", {"command": "pwd"}))
        self.assertFalse(runner.should_run_background("read_file", {"path": "x"}))

    def test_example_script_does_not_trigger_background_execution(self):
        runner = BackgroundTaskRunner(lambda block: "done")

        self.assertFalse(
            runner.should_run_background(
                "bash",
                {"command": ("cd /project/examples && python3 calculator.py")},
            )
        )

    def test_tool_call_shape_matches_loop_usage(self):
        block = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(
                name="bash",
                arguments='{"command": "npm install", "run_in_background": true}',
            ),
        )
        runner = BackgroundTaskRunner(lambda block: "done")

        self.assertTrue(runner.should_run_tool_call(block))
        runner.start(block)

        notification = self._wait_for_notifications(runner)[0]
        self.assertIn("<command>npm install</command>", notification)

    def _wait_for_notifications(self, runner: BackgroundTaskRunner) -> list[str]:
        deadline = time.time() + 2
        while time.time() < deadline:
            notifications = runner.collect_completed()
            if notifications:
                return notifications
            time.sleep(0.01)
        self.fail("Timed out waiting for background task notification")


if __name__ == "__main__":
    unittest.main()
