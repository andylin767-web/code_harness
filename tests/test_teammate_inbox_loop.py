import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from code_harness.core.agent import Agent, LeadAgent
from code_harness.events.runtime import set_event_queue
from code_harness.team.message_bus import MessageBus
from code_harness.team.protocol_state import ProtocolType


class TeammateInboxLoopTests(unittest.TestCase):
    def tearDown(self):
        set_event_queue(None)

    def test_completed_teammate_waits_and_dispatches_until_shutdown(self):
        calls = []
        call_events = [threading.Event() for _ in range(3)]

        class FakeLoopStatus:
            COMPLETED = "completed"
            MAX_RUNS = "max_runs"

        class FakeLoop:
            def __init__(self, agent, permission_engine, max_runs=20):
                self.system_prompt = "system prompt"
                self.max_runs = max_runs

            async def run(self, store, conversation_id, user_message):
                calls.append(user_message)
                call_events[len(calls) - 1].set()
                return SimpleNamespace(
                    status=FakeLoopStatus.COMPLETED,
                    summary=f"response {len(calls)}",
                )

        fake_loop_module = types.ModuleType("code_harness.core.loop")
        fake_loop_module.Loop = FakeLoop
        fake_loop_module.LoopStatus = FakeLoopStatus

        lead = LeadAgent(
            name="lead",
            role="lead",
            assignment="coordinate",
            toolset=Mock(),
            system_prompt="",
            model="test-model",
            teammate_inbox_poll_interval=0.01,
        )
        teammate = Agent(
            name="reviewer",
            role="reviewer",
            assignment="Review the implementation",
            toolset=Mock(),
            system_prompt="",
            model="test-model",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir) / "mailboxes")
            result = []
            errors = []

            def run_teammate():
                try:
                    result.append(
                        lead._run_sub_agent(
                            teammate,
                            "conv-parent",
                            bus,
                        )
                    )
                except Exception as exc:  # pragma: no cover - assertion aid
                    errors.append(exc)

            with (
                patch.dict(
                    sys.modules,
                    {"code_harness.core.loop": fake_loop_module},
                ),
                patch(
                    "code_harness.core.permissions."
                    "PermissionEngine.load_settings_json"
                ),
                patch("code_harness.core.tracing.save_trace"),
            ):
                thread = threading.Thread(target=run_teammate)
                thread.start()
                self.assertTrue(call_events[0].wait(timeout=1))

                bus.send(
                    from_agent="lead",
                    to_agent="reviewer",
                    content="Approved",
                    msg_type=ProtocolType.PLAN_APPROVAL_RESPONSE,
                    metadata={"request_id": "req_plan", "approve": True},
                )
                self.assertTrue(call_events[1].wait(timeout=1))

                bus.send(
                    from_agent="lead",
                    to_agent="reviewer",
                    content="Check the rollback path",
                )
                self.assertTrue(call_events[2].wait(timeout=1))

                bus.send(
                    from_agent="lead",
                    to_agent="reviewer",
                    content="Please shut down",
                    msg_type=ProtocolType.SHUTDOWN_REQUEST,
                    metadata={"request_id": "req_shutdown"},
                )
                thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, [None])
            self.assertEqual(calls[0], "Review the implementation")
            self.assertIn("[Plan approved]", calls[1])
            self.assertIn("<inbox>", calls[2])
            self.assertIn("Check the rollback path", calls[2])

            lead_messages = bus.read_inbox("lead")
            shutdown_responses = [
                message
                for message in lead_messages
                if message["type"] == ProtocolType.SHUTDOWN_RESPONSE
            ]
            self.assertEqual(
                len(shutdown_responses),
                1,
            )
            self.assertEqual(
                shutdown_responses[0]["metadata"],
                {"request_id": "req_shutdown", "approve": True},
            )
            result_messages = [
                message
                for message in lead_messages
                if message["type"] == "result"
            ]
            self.assertEqual(len(result_messages), 1)
            self.assertEqual(result_messages[0]["content"], "response 3")
            self.assertEqual(
                result_messages[0]["metadata"],
                {"exit_status": "shutdown"},
            )

    def test_max_runs_work_phase_still_enters_idle_and_wakes_for_message(self):
        calls = []
        call_events = [threading.Event() for _ in range(2)]

        class FakeLoopStatus:
            COMPLETED = "completed"
            MAX_RUNS = "max_runs"

        class FakeLoop:
            def __init__(self, agent, permission_engine, max_runs=20):
                self.system_prompt = "system prompt"

            async def run(self, store, conversation_id, user_message):
                calls.append(user_message)
                call_events[len(calls) - 1].set()
                return SimpleNamespace(
                    status=(
                        FakeLoopStatus.MAX_RUNS
                        if len(calls) == 1
                        else FakeLoopStatus.COMPLETED
                    ),
                    summary=f"response {len(calls)}",
                )

        fake_loop_module = types.ModuleType("code_harness.core.loop")
        fake_loop_module.Loop = FakeLoop
        fake_loop_module.LoopStatus = FakeLoopStatus

        lead = LeadAgent(
            name="lead",
            role="lead",
            assignment="coordinate",
            toolset=Mock(),
            system_prompt="",
            model="test-model",
            teammate_inbox_poll_interval=0.01,
        )
        teammate = Agent(
            name="reviewer",
            role="reviewer",
            assignment="Review the implementation",
            toolset=Mock(),
            system_prompt="",
            model="test-model",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(Path(tmpdir) / "mailboxes")
            errors = []

            def run_teammate():
                try:
                    lead._run_sub_agent(teammate, "conv-parent", bus)
                except Exception as exc:  # pragma: no cover - assertion aid
                    errors.append(exc)

            with (
                patch.dict(
                    sys.modules,
                    {"code_harness.core.loop": fake_loop_module},
                ),
                patch(
                    "code_harness.core.permissions."
                    "PermissionEngine.load_settings_json"
                ),
                patch("code_harness.core.tracing.save_trace"),
            ):
                thread = threading.Thread(target=run_teammate)
                thread.start()
                self.assertTrue(call_events[0].wait(timeout=1))

                bus.send(
                    from_agent="lead",
                    to_agent="reviewer",
                    content="Continue with this follow-up",
                )
                self.assertTrue(call_events[1].wait(timeout=1))

                bus.send(
                    from_agent="lead",
                    to_agent="reviewer",
                    content="Please shut down",
                    msg_type=ProtocolType.SHUTDOWN_REQUEST,
                    metadata={"request_id": "req_shutdown"},
                )
                thread.join(timeout=1)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertIn("Continue with this follow-up", calls[1])


if __name__ == "__main__":
    unittest.main()
