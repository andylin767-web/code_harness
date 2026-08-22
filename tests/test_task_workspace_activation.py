from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from code_harness.core.agent import (
    Agent,
    LeadAgent,
    idle_poll,
    resolve_task_workspace,
)
from code_harness.core.permissions import PermissionEngine
from code_harness.core.worktrees import TARGET_REPOSITORY_ROOT
from code_harness.team.message_bus import MessageBus
from code_harness.team.protocol_dispatcher import ProtocolDispatcher
from code_harness.tools.task_system import TaskManager


class TaskWorkspaceResolutionTests(TestCase):
    @patch("code_harness.core.worktrees.manager")
    def test_resolves_existing_git_worktree(self, manager):
        with TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            (worktree / ".git").write_text("gitdir: test")
            manager.worktree_path.return_value = worktree
            task = SimpleNamespace(id="task_1", worktree="feature")

            result = resolve_task_workspace(task)

            self.assertEqual(result, worktree.resolve())

    @patch("code_harness.core.worktrees.manager")
    def test_missing_worktree_fails_closed(self, manager):
        manager.worktree_path.return_value = Path("/missing/worktree")
        task = SimpleNamespace(id="task_1", worktree="feature")

        with self.assertRaisesRegex(FileNotFoundError, "Recreate or rebind"):
            resolve_task_workspace(task)

    def test_task_without_worktree_uses_target_repository(self):
        task = SimpleNamespace(id="task_1", worktree=None)

        self.assertEqual(resolve_task_workspace(task), TARGET_REPOSITORY_ROOT)

    def test_activation_switches_agent_and_permission_engine(self):
        with TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir)
            (worktree / ".git").write_text("gitdir: test")
            agent = Agent("worker", "dev", "work", object(), "", "model")
            permissions = PermissionEngine()
            task = SimpleNamespace(id="task_1", worktree="feature")

            with patch(
                "code_harness.core.worktrees.WorktreeManager.worktree_path",
                return_value=worktree,
            ):
                result = LeadAgent._activate_task_workspace(
                    agent,
                    permissions,
                    task,
                )

            self.assertEqual(result, worktree.resolve())
            self.assertEqual(agent.workspace_root, worktree.resolve())
            self.assertEqual(permissions.workspace_root, worktree.resolve())

    def test_task_without_worktree_resets_agent_to_target_repository(self):
        with TemporaryDirectory() as tmpdir:
            agent = Agent(
                "worker",
                "dev",
                "work",
                object(),
                "",
                "model",
                workspace_root=Path(tmpdir),
            )
            permissions = PermissionEngine(workspace_root=Path(tmpdir))
            task = SimpleNamespace(id="task_1", worktree=None)

            LeadAgent._activate_task_workspace(agent, permissions, task)

            self.assertEqual(agent.workspace_root, TARGET_REPOSITORY_ROOT)
            self.assertEqual(
                permissions.workspace_root,
                TARGET_REPOSITORY_ROOT,
            )


class TaskWorkspaceIdlePollTests(IsolatedAsyncioTestCase):
    async def test_claimed_task_activates_workspace_before_message(self):
        with TemporaryDirectory() as tasks_dir, TemporaryDirectory() as workspace:
            task_manager = TaskManager(Path(tasks_dir))
            task_manager.create_task("Implement feature", "")
            selected = []
            bus = Mock(spec=MessageBus)
            bus.read_inbox.return_value = []
            dispatcher = Mock(spec=ProtocolDispatcher)
            messages = []

            status = await idle_poll(
                "worker",
                messages,
                "developer",
                message_bus=bus,
                teammate_dispatcher=dispatcher,
                task_manager=task_manager,
                on_task_selected=lambda task: (
                    selected.append(task.id) or Path(workspace).resolve()
                ),
                timeout_seconds=1,
                poll_interval=0,
            )

            self.assertEqual(status, "work")
            self.assertEqual(selected, [task_manager.list_tasks()[0].id])
            self.assertIn(str(Path(workspace).resolve()), messages[0]["content"])

    async def test_activation_failure_stops_claimed_task_work(self):
        with TemporaryDirectory() as tasks_dir:
            task_manager = TaskManager(Path(tasks_dir))
            task_manager.create_task("Implement feature", "")
            bus = Mock(spec=MessageBus)
            bus.read_inbox.return_value = []
            dispatcher = Mock(spec=ProtocolDispatcher)
            messages = []

            def fail_activation(task):
                raise FileNotFoundError(
                    f"Task {task.id} worktree is missing. Recreate or rebind it."
                )

            status = await idle_poll(
                "worker",
                messages,
                "developer",
                message_bus=bus,
                teammate_dispatcher=dispatcher,
                task_manager=task_manager,
                on_task_selected=fail_activation,
                timeout_seconds=1,
                poll_interval=0,
            )

            task = task_manager.list_tasks()[0]
            self.assertEqual(status, "workspace_error")
            self.assertEqual(task.status, "in_progress")
            self.assertEqual(task.owner, "worker")
            self.assertIn("Recreate or rebind", messages[0]["content"])
