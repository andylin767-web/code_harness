import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from code_harness.core.worktrees import (
    MANAGED_WORKTREES_ROOT,
    TARGET_REPOSITORY_ROOT,
    WorktreeManager,
    manager,
)


class WorktreeManagerTests(TestCase):
    def test_shared_manager_uses_configured_target_repository(self):
        self.assertEqual(manager.repo_root, TARGET_REPOSITORY_ROOT)
        self.assertEqual(manager.worktrees_dir, MANAGED_WORKTREES_ROOT)

    def test_rejects_invalid_worktree_name(self):
        manager = WorktreeManager()

        with self.assertRaises(ValueError):
            manager.worktree_path("../outside")

    def test_binds_task_to_worktree(self):
        task = SimpleNamespace(worktree=None)
        task_manager = Mock()
        task_manager.load_task.return_value = task
        manager = WorktreeManager(task_manager=task_manager)

        result = manager.bind_task_to_worktree("task_1", "feature")

        self.assertEqual(task.worktree, "feature")
        task_manager.save_task.assert_called_once_with(task)
        self.assertEqual(result, "Task task_1 bound to worktree feature")


class AsyncWorktreeManagerTests(IsolatedAsyncioTestCase):
    async def test_run_git_uses_async_subprocess(self):
        repo_root = Path("/tmp/repository")
        process = Mock(returncode=0)
        process.communicate = AsyncMock(return_value=(b"output", b" warning"))

        with patch(
            "code_harness.core.worktrees.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as create_process:
            manager = WorktreeManager(repo_root=repo_root)
            ok, output = await manager.run_git(["status", "--short"])

        self.assertTrue(ok)
        self.assertEqual(output, "output warning")
        create_process.assert_awaited_once_with(
            "git",
            "status",
            "--short",
            cwd=manager.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def test_count_worktree_changes_uses_async_git_calls(self):
        manager = WorktreeManager(repo_root=Path("/tmp/repository"))
        path = manager.worktree_path("feature")
        manager.run_git = AsyncMock(
            side_effect=[
                (True, " M changed.py\n?? new.py\n"),
                (True, "abc123 First commit\ndef456 Second commit\n"),
            ]
        )

        files, commits = await manager._count_worktree_changes(path)

        self.assertEqual((files, commits), (2, 2))
        self.assertEqual(manager.run_git.await_count, 2)
        manager.run_git.assert_any_await(
            ["status", "--porcelain"],
            cwd=path,
            timeout=10,
        )
        manager.run_git.assert_any_await(
            ["log", "@{push}..HEAD", "--oneline"],
            cwd=path,
            timeout=10,
        )

    async def test_remove_worktree_awaits_change_count(self):
        manager = WorktreeManager(repo_root=Path("/tmp/repository"))
        manager._count_worktree_changes = AsyncMock(return_value=(1, 0))
        manager.run_git = AsyncMock()

        result = await manager.remove_worktree("feature")

        self.assertIn("Worktree has changes", result)
        manager._count_worktree_changes.assert_awaited_once_with(
            manager.worktree_path("feature")
        )
        manager.run_git.assert_not_awaited()

    async def test_create_worktree_awaits_git_and_binds_task(self):
        repo_root = Path("/tmp/repository")
        with TemporaryDirectory() as temp_dir:
            worktrees_dir = Path(temp_dir)
            task_manager = Mock()
            task_manager.load_task.return_value = SimpleNamespace(worktree=None)
            manager = WorktreeManager(
                repo_root=repo_root,
                worktrees_dir=worktrees_dir,
                task_manager=task_manager,
            )
            manager.run_git = AsyncMock(return_value=(True, ""))

            result = await manager.create_worktree("feature", "task_1")

            manager.run_git.assert_awaited_once_with(
                [
                    "worktree",
                    "add",
                    "-b",
                    "wt/feature",
                    str(manager.worktrees_dir / "feature"),
                    "HEAD",
                ]
            )
            self.assertIn("Worktree 'feature' created", result)
            task_manager.save_task.assert_called_once()
            events = [
                json.loads(line)
                for line in manager.event_log_path.read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["action"], "create")
            self.assertEqual(events[0]["worktree"], "feature")
            self.assertEqual(events[0]["task_id"], "task_1")
            self.assertEqual(
                events[0]["path"],
                str(manager.worktrees_dir / "feature"),
            )

    async def test_failed_creation_does_not_log_event(self):
        with TemporaryDirectory() as temp_dir:
            manager = WorktreeManager(
                repo_root=Path(temp_dir),
                worktrees_dir=Path(temp_dir) / "worktrees",
            )
            manager.run_git = AsyncMock(return_value=(False, "failed"))

            result = await manager.create_worktree("feature")

            self.assertEqual(result, "Git error: failed")
            self.assertFalse(manager.event_log_path.exists())
