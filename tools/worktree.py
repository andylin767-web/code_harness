from pydantic import BaseModel, Field

from code_harness.core.worktrees import manager
from code_harness.tools.tools import BaseTool


class CreateWorktreeInput(BaseModel):
    name: str = Field(description="Short name for the managed worktree.")
    task_id: str = Field(
        default="",
        description="Optional task ID to bind to the new worktree.",
    )


class RemoveWorktreeInput(BaseModel):
    name: str = Field(description="Name of the managed worktree to remove.")
    discard_changes: bool = Field(
        default=False,
        description="Force removal even when the worktree has changes.",
    )


class KeepWorktreeInput(BaseModel):
    name: str = Field(description="Name of the worktree to retain for review.")


class CreateWorktreeTool(BaseTool):
    name = "create_worktree"
    description = "Create a managed Git worktree and optionally bind it to a task."
    input_model = CreateWorktreeInput
    agent_types = {"parent"}

    def __init__(self, services=None):
        self.manager = (
            services.worktree_manager
            if services is not None and services.worktree_manager is not None
            else manager
        )

    async def run(self, arguments: CreateWorktreeInput) -> str:
        return await self.manager.create_worktree(
            arguments.name,
            arguments.task_id,
        )


class RemoveWorktreeTool(BaseTool):
    name = "remove_worktree"
    description = (
        "Remove a managed Git worktree if it is clean, or explicitly discard "
        "its changes."
    )
    input_model = RemoveWorktreeInput
    agent_types = {"parent"}

    def __init__(self, services=None):
        self.manager = (
            services.worktree_manager
            if services is not None and services.worktree_manager is not None
            else manager
        )

    async def run(self, arguments: RemoveWorktreeInput) -> str:
        return await self.manager.remove_worktree(
            arguments.name,
            discard_changes=arguments.discard_changes,
        )


class KeepWorktreeTool(BaseTool):
    name = "keep_worktree"
    description = "Keep a managed Git worktree for review and log that decision."
    input_model = KeepWorktreeInput
    agent_types = {"parent"}

    def __init__(self, services=None):
        self.manager = (
            services.worktree_manager
            if services is not None and services.worktree_manager is not None
            else manager
        )

    def run(self, arguments: KeepWorktreeInput) -> str:
        return self.manager.keep_worktree(arguments.name)
