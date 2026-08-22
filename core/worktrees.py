import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import threading
from typing import Any
from uuid import uuid4

from code_harness.core.permissions import PROJECT_ROOT


WORKTREE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_event_log_lock = threading.RLock()
TARGET_REPOSITORY_ROOT = Path(
    "/path/to/work-tree-repository"
).resolve()
MANAGED_WORKTREES_ROOT = (PROJECT_ROOT / ".worktrees").resolve()


class WorktreeManager:
    """Create Git worktrees and associate them with harness tasks."""

    def __init__(
        self,
        repo_root: Path = PROJECT_ROOT,
        worktrees_dir: Path | None = None,
        task_manager: Any | None = None,
        event_log_path: Path | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.worktrees_dir = (
            worktrees_dir or self.repo_root / ".worktrees"
        ).resolve()
        self.task_manager = task_manager
        self.event_log_path = (
            event_log_path or self.worktrees_dir / "events.jsonl"
        ).resolve()

    @staticmethod
    def validate_worktree_name(name: str) -> None:
        if not WORKTREE_NAME_RE.fullmatch(name):
            raise ValueError("Invalid worktree name")

    def worktree_path(self, name: str) -> Path:
        self.validate_worktree_name(name)
        path = (self.worktrees_dir / name).resolve()
        if not path.is_relative_to(self.worktrees_dir):
            raise ValueError("Worktree path escapes managed directory")
        return path

    async def run_git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> tuple[bool, str]:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd or self.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise

        output = (stdout + stderr).decode(errors="replace")
        return process.returncode == 0, output

    def log_event(
        self,
        action: str,
        name: str,
        *,
        task_id: str = "",
        path: Path | None = None,
    ) -> None:
        """Append a structured worktree lifecycle event to the audit log."""
        self.validate_worktree_name(name)
        event = {
            "event_id": f"worktree_{uuid4().hex}",
            "action": action,
            "worktree": name,
            "task_id": task_id or None,
            "path": str(path or self.worktree_path(name)),
            "created_at": datetime.now(UTC).isoformat(),
        }

        with _event_log_lock:
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(event) + "\n")

    async def create_worktree(self, name: str, task_id: str = "") -> str:
        path = self.worktree_path(name)
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        branch = f"wt/{name}"

        ok, result = await self.run_git(
            [
                "worktree",
                "add",
                "-b",
                branch,
                str(path),
                "HEAD",
            ]
        )
        if not ok:
            return f"Git error: {result}"

        self.log_event("create", name, task_id=task_id, path=path)

        if task_id:
            self.bind_task_to_worktree(task_id, name)

        return f"Worktree '{name}' created at {path}"

    def bind_task_to_worktree(self, task_id: str, worktree_name: str) -> str:
        self.validate_worktree_name(worktree_name)
        task_manager = self.task_manager
        if task_manager is None:
            from code_harness.tools.task_system import TaskManager

            task_manager = TaskManager()

        task = task_manager.load_task(task_id)
        task.worktree = worktree_name
        task_manager.save_task(task)
        return f"Task {task_id} bound to worktree {worktree_name}"

    def keep_worktree(self, name: str) -> str:
        self.validate_worktree_name(name)
        self.log_event("keep", name)
        return f"Worktree '{name}' kept for review"
    

    async def _count_worktree_changes(self, path: Path) -> tuple[int, int]:
        """Count uncommitted files and commits in a worktree."""
        try:
            status_result, log_result = await asyncio.gather(
                self.run_git(
                    ["status", "--porcelain"],
                    cwd=path,
                    timeout=10,
                ),
                self.run_git(
                    ["log", "@{push}..HEAD", "--oneline"],
                    cwd=path,
                    timeout=10,
                ),
            )
            status_ok, status_output = status_result
            log_ok, log_output = log_result
            files = len(status_output.splitlines()) if status_ok else 0
            commits = len(log_output.splitlines()) if log_ok else 0
            return files, commits
        except Exception:
            return -1, -1

    async def remove_worktree(
        self,
        name: str,
        discard_changes: bool = False,
    ) -> str:
        self.validate_worktree_name(name)

        path = self.worktree_path(name)

        if not discard_changes:
            files, commits = await self._count_worktree_changes(path)

            if files > 0 or commits > 0:
                return (
                    "Worktree has changes. "
                    "Use discard_changes=True to force, "
                    "or keep_worktree for review."
                )

        ok, result = await self.run_git(
            [
                "worktree",
                "remove",
                str(path),
                "--force",
            ]
        )

        if not ok:
            return f"Remove failed: {result}"

        await self.run_git(["branch", "-D", f"wt/{name}"])

        self.log_event("remove", name)

        return f"Worktree '{name}' removed"


# All worktree lifecycle operations and teammate lookups share this manager so
# they resolve names against the same target repository and worktree directory.
manager = WorktreeManager(
    repo_root=TARGET_REPOSITORY_ROOT,
    worktrees_dir=MANAGED_WORKTREES_ROOT,
)
