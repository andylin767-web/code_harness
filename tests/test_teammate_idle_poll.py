import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from code_harness.core.agent import idle_poll
from code_harness.team.message_bus import MessageBus
from code_harness.team.protocol_dispatcher import ProtocolDispatcher
from code_harness.tools.task_system import TaskManager


class TeammateIdlePollTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_is_handled_before_normal_messages(self):
        bus = Mock(spec=MessageBus)
        bus.read_inbox.return_value = [
            {"type": "message", "content": "More work"},
            {"type": "shutdown_request", "content": "Stop"},
        ]
        dispatcher = Mock(spec=ProtocolDispatcher)
        dispatcher.dispatch.return_value = True
        task_manager = Mock(spec=TaskManager)
        messages = []

        status = await idle_poll(
            "reviewer",
            messages,
            "reviewer",
            message_bus=bus,
            teammate_dispatcher=dispatcher,
            task_manager=task_manager,
            timeout_seconds=1,
            poll_interval=0,
        )

        self.assertEqual(status, "shutdown")
        dispatcher.dispatch.assert_called_once_with(
            "reviewer",
            {"type": "shutdown_request", "content": "Stop"},
            messages,
        )
        task_manager.scan_unclaimed_tasks.assert_not_called()

    async def test_claims_available_task_and_injects_work_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_manager = TaskManager(Path(tmpdir))
            task_manager.create_task("Review authentication", "")
            bus = Mock(spec=MessageBus)
            bus.read_inbox.return_value = []
            dispatcher = Mock(spec=ProtocolDispatcher)
            messages = []

            status = await idle_poll(
                "reviewer",
                messages,
                "reviewer",
                message_bus=bus,
                teammate_dispatcher=dispatcher,
                task_manager=task_manager,
                timeout_seconds=1,
                poll_interval=0,
            )

            self.assertEqual(status, "work")
            task = task_manager.list_tasks()[0]
            self.assertEqual(
                messages,
                [
                    {
                        "role": "user",
                        "content": (
                            "You claimed a task from the shared task board.\n"
                            f"Task ID: {task.id}\n"
                            "Subject: Review authentication\n"
                            "Description: \n"
                            f"Active workspace: {Path(__file__).resolve().parents[1]}\n\n"
                            "Complete this task now. When the work is finished, "
                            "call complete_task with this task ID and your name "
                            "(reviewer) as owner."
                        ),
                    }
                ],
            )
            self.assertEqual(task.status, "in_progress")
            self.assertEqual(task.owner, "reviewer")

    async def test_normal_message_returns_to_work_before_task_scan(self):
        bus = Mock(spec=MessageBus)
        message = {"type": "message", "content": "Review the new change"}
        bus.read_inbox.return_value = [message]
        dispatcher = Mock(spec=ProtocolDispatcher)
        dispatcher.dispatch.return_value = False
        task_manager = Mock(spec=TaskManager)
        messages = []

        status = await idle_poll(
            "reviewer",
            messages,
            "reviewer",
            message_bus=bus,
            teammate_dispatcher=dispatcher,
            task_manager=task_manager,
            timeout_seconds=1,
            poll_interval=0,
        )

        self.assertEqual(status, "work")
        dispatcher.dispatch.assert_called_once_with(
            "reviewer",
            message,
            messages,
        )
        task_manager.scan_unclaimed_tasks.assert_not_called()

    async def test_tries_next_task_when_first_claim_loses_race(self):
        first_task = Mock(id="task_1", subject="First", description="First work")
        second_task = Mock(
            id="task_2",
            subject="Second",
            description="Second work",
        )
        task_manager = Mock(spec=TaskManager)
        task_manager.scan_in_progress_tasks.return_value = []
        task_manager.scan_unclaimed_tasks.return_value = [
            first_task,
            second_task,
        ]
        task_manager.claim_task.side_effect = [
            "Task task_1 is in_progress, cannot claim",
            "Claimed task_2 (Second)",
        ]
        bus = Mock(spec=MessageBus)
        bus.read_inbox.return_value = []
        dispatcher = Mock(spec=ProtocolDispatcher)
        messages = []

        status = await idle_poll(
            "reviewer",
            messages,
            "reviewer",
            message_bus=bus,
            teammate_dispatcher=dispatcher,
            task_manager=task_manager,
            timeout_seconds=1,
            poll_interval=0,
        )

        self.assertEqual(status, "work")
        self.assertEqual(
            task_manager.claim_task.call_args_list,
            [
                unittest.mock.call("task_1", owner="reviewer"),
                unittest.mock.call("task_2", owner="reviewer"),
            ],
        )
        self.assertEqual(
            messages,
            [
                {
                    "role": "user",
                    "content": (
                        "You claimed a task from the shared task board.\n"
                        "Task ID: task_2\n"
                        "Subject: Second\n"
                        "Description: Second work\n"
                        f"Active workspace: {Path(__file__).resolve().parents[1]}\n\n"
                        "Complete this task now. When the work is finished, "
                        "call complete_task with this task ID and your name "
                        "(reviewer) as owner."
                    ),
                }
            ],
        )

    async def test_resumes_owned_task_before_claiming_new_task(self):
        owned_task = Mock(
            id="task_owned",
            subject="Owned task",
            description="Finish the existing implementation",
        )
        task_manager = Mock(spec=TaskManager)
        task_manager.scan_in_progress_tasks.return_value = [owned_task]
        bus = Mock(spec=MessageBus)
        bus.read_inbox.return_value = []
        dispatcher = Mock(spec=ProtocolDispatcher)
        messages = []

        status = await idle_poll(
            "reviewer",
            messages,
            "reviewer",
            message_bus=bus,
            teammate_dispatcher=dispatcher,
            task_manager=task_manager,
            timeout_seconds=1,
            poll_interval=0,
        )

        self.assertEqual(status, "work")
        self.assertIn("You already own", messages[0]["content"])
        self.assertIn("Task ID: task_owned", messages[0]["content"])
        self.assertIn("call complete_task", messages[0]["content"])
        task_manager.scan_unclaimed_tasks.assert_not_called()

    async def test_returns_timeout_without_polling_when_window_is_zero(self):
        bus = Mock(spec=MessageBus)
        dispatcher = Mock(spec=ProtocolDispatcher)
        task_manager = Mock(spec=TaskManager)

        status = await idle_poll(
            "reviewer",
            [],
            "reviewer",
            message_bus=bus,
            teammate_dispatcher=dispatcher,
            task_manager=task_manager,
            timeout_seconds=0,
            poll_interval=0,
        )

        self.assertEqual(status, "timeout")
        bus.read_inbox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
