from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from code_harness.tools.worktree import (
    CreateWorktreeInput,
    CreateWorktreeTool,
    KeepWorktreeInput,
    KeepWorktreeTool,
    RemoveWorktreeInput,
    RemoveWorktreeTool,
)


class AsyncWorktreeToolTests(IsolatedAsyncioTestCase):
    @patch("code_harness.tools.worktree.manager")
    async def test_create_worktree_delegates_to_manager(self, manager):
        manager.create_worktree = AsyncMock(return_value="created")

        result = await CreateWorktreeTool().run(
            CreateWorktreeInput(name="feature", task_id="task_1")
        )

        self.assertEqual(result, "created")
        manager.create_worktree.assert_awaited_once_with("feature", "task_1")

    @patch("code_harness.tools.worktree.manager")
    async def test_remove_worktree_delegates_to_manager(self, manager):
        manager.remove_worktree = AsyncMock(return_value="removed")

        result = await RemoveWorktreeTool().run(
            RemoveWorktreeInput(name="feature", discard_changes=True)
        )

        self.assertEqual(result, "removed")
        manager.remove_worktree.assert_awaited_once_with(
            "feature",
            discard_changes=True,
        )


class WorktreeToolTests(TestCase):
    @patch("code_harness.tools.worktree.manager")
    def test_keep_worktree_delegates_to_manager(self, manager):
        manager.keep_worktree = Mock(return_value="kept")

        result = KeepWorktreeTool().run(KeepWorktreeInput(name="feature"))

        self.assertEqual(result, "kept")
        manager.keep_worktree.assert_called_once_with("feature")
