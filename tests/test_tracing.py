import json
import tempfile
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from code_harness.core import tracing
from code_harness.memory.context import MessageRecord


class TracingTests(unittest.TestCase):
    def test_nested_llm_calls_recorded_from_child_task_are_visible_to_parent(self):
        async def run_child_task():
            tracing.init_nested_llm_calls()

            async def child():
                tracing.record_nested_llm_call({"file_path": "core/loop.py"})

            await asyncio.create_task(child())
            return tracing.pop_nested_llm_calls()

        events = asyncio.run(run_child_task())

        self.assertEqual(events, [{"file_path": "core/loop.py"}])

    def test_save_trace_includes_and_clears_nested_llm_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_dir = Path(tmpdir)
            tracing.record_nested_llm_call(
                {
                    "type": "llm_summarize_python_file",
                    "file_path": "core/loop.py",
                    "status": "ok",
                }
            )

            with patch.object(tracing, "TRACE_DIR", trace_dir):
                trace_path = tracing.save_trace(
                    run_id="run-1",
                    started_at="start",
                    ended_at="end",
                    user_input="summarize",
                    conversation_id="conversation-1",
                    messages=[
                        MessageRecord.user(
                            conversation_id="conversation-1",
                            content="summarize",
                        )
                    ],
                )
                second_trace_path = tracing.save_trace(
                    run_id="run-2",
                    started_at="start",
                    ended_at="end",
                    user_input="next",
                    conversation_id="conversation-1",
                    messages=[],
                )

            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            second_trace = json.loads(second_trace_path.read_text(encoding="utf-8"))

            self.assertEqual(trace["nested_llm_calls"][0]["file_path"], "core/loop.py")
            self.assertEqual(second_trace["nested_llm_calls"], [])

if __name__ == "__main__":
    unittest.main()
