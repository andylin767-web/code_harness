import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from code_harness.core.agent import LeadAgent


class TeammateLifecycleTests(unittest.TestCase):
    def _lead_agent(self) -> LeadAgent:
        return LeadAgent(
            name="lead",
            role="lead",
            assignment="coordinate",
            toolset=Mock(),
            system_prompt="",
            model="test-model",
        )

    def _wait_until_inactive(self, lead: LeadAgent, name: str) -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            with lead._teammate_lock:
                if not any(agent.name == name for agent in lead.subagents):
                    return
            time.sleep(0.01)
        self.fail(f"Timed out waiting for teammate {name} to finish")

    def test_teammate_finishes_without_empty_inbox_polling_delay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lead = self._lead_agent()
            run_subagent = Mock(return_value=Mock(summary="done"))
            lead._run_sub_agent = run_subagent

            with patch(
                "code_harness.core.permissions.PROJECT_ROOT",
                Path(tmpdir),
            ):
                lead.spawn_teammate_thread(
                    "reviewer",
                    "reviewer",
                    "Review the change",
                    "conv-parent",
                )
                self._wait_until_inactive(lead, "reviewer")

            self.assertEqual(run_subagent.call_count, 1)

    def test_shutdown_signal_exits_without_processing_more_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lead = self._lead_agent()
            run_subagent = Mock(return_value=None)
            lead._run_sub_agent = run_subagent

            with patch(
                "code_harness.core.permissions.PROJECT_ROOT",
                Path(tmpdir),
            ):
                lead.spawn_teammate_thread(
                    "reviewer",
                    "reviewer",
                    "Review the change",
                    "conv-parent",
                )
                self._wait_until_inactive(lead, "reviewer")

            self.assertEqual(run_subagent.call_count, 1)

    def test_message_restarts_a_completed_teammate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lead = self._lead_agent()
            run_subagent = Mock(return_value=Mock(summary="done"))
            lead._run_sub_agent = run_subagent

            with patch(
                "code_harness.core.permissions.PROJECT_ROOT",
                Path(tmpdir),
            ):
                lead.spawn_teammate_thread(
                    "reviewer",
                    "reviewer",
                    "Initial review",
                    "conv-parent",
                )
                self._wait_until_inactive(lead, "reviewer")

                result = lead.send_teammate_message(
                    "reviewer",
                    "Please check the tests too",
                )
                self._wait_until_inactive(lead, "reviewer")

            self.assertEqual(
                result,
                "Restarted teammate reviewer with follow-up message",
            )
            self.assertEqual(run_subagent.call_count, 2)
            restarted_agent = run_subagent.call_args_list[1].kwargs["sub_agent"]
            self.assertEqual(
                restarted_agent.assignment,
                "Please check the tests too",
            )

    def test_message_arriving_during_run_is_processed_without_sleeping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lead = self._lead_agent()
            first_run_started = threading.Event()
            allow_first_run_to_finish = threading.Event()
            call_count = 0

            def run_subagent(*, sub_agent, parent_conversation_id, message_bus):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    first_run_started.set()
                    allow_first_run_to_finish.wait(timeout=2)
                else:
                    messages = message_bus.read_inbox(sub_agent.name)
                    self.assertEqual(messages[0]["content"], "Follow up")
                return Mock(summary="done")

            lead._run_sub_agent = run_subagent

            with patch(
                "code_harness.core.permissions.PROJECT_ROOT",
                Path(tmpdir),
            ):
                lead.spawn_teammate_thread(
                    "reviewer",
                    "reviewer",
                    "Initial review",
                    "conv-parent",
                )
                self.assertTrue(first_run_started.wait(timeout=2))
                self.assertEqual(
                    lead.send_teammate_message("reviewer", "Follow up"),
                    "Sent message to reviewer",
                )
                allow_first_run_to_finish.set()
                self._wait_until_inactive(lead, "reviewer")

            self.assertEqual(call_count, 2)


if __name__ == "__main__":
    unittest.main()
