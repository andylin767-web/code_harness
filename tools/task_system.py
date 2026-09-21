import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from code_harness.tools.tools import BaseTool

_task_locks_guard = threading.Lock()
_task_locks: dict[Path, threading.RLock] = {}


def _thread_lock_for(tasks_dir: Path) -> threading.RLock:
    resolved_dir = tasks_dir.resolve()
    with _task_locks_guard:
        return _task_locks.setdefault(resolved_dir, threading.RLock())


@contextmanager
def _exclusive_file_lock(path: Path):
    """Hold an exclusive cross-process lock for the given lock file."""
    with path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str  # pending | in_progress | completed
    owner: str | None  # Agent name (multi-agent scenarios)
    blockedBy: list[str]  # Dependency task IDs
    worktree: str | None = None


class TaskManager:
    def __init__(self, tasks_dir: Path | None = None):
        self.TASKS_DIR = tasks_dir or Path(__file__).resolve().parents[1] / ".tasks"
        self.TASKS_DIR.mkdir(parents=True, exist_ok=True)
        self._claim_lock_path = self.TASKS_DIR / ".claim.lock"
        self._claim_thread_lock = _thread_lock_for(self.TASKS_DIR)

    def _task_path(self, task_id: str) -> Path:
        return self.TASKS_DIR / f"{task_id}.json"

    def save_task(self, task: Task):
        self._task_path(task.id).write_text(json.dumps(asdict(task), indent=2))

    def load_task(self, task_id: str) -> Task:
        return Task(**json.loads(self._task_path(task_id).read_text()))

    def list_tasks(self) -> list[Task]:
        return [
            Task(**json.loads(p.read_text()))
            for p in sorted(self.TASKS_DIR.glob("task_*.json"))
        ]

    def create_task(
        self,
        subject: str,
        description: str,
        blockedBy: list[str] | None = None,
        task_id: str | None = None,
    ) -> str:
        task = Task(
            id=task_id or f"task_{uuid4().hex[:12]}",
            subject=subject,
            description=description,
            status="pending",
            owner=None,
            blockedBy=blockedBy or [],
        )
        self.save_task(task)
        return json.dumps(asdict(task), indent=2)

    def get_task(self, task_id: str) -> str:
        """Return full task details as JSON."""
        task = self.load_task(task_id)
        return json.dumps(asdict(task), indent=2)

    def can_start(self, task_id: str) -> bool:
        """Check if all blockedBy dependencies are completed.
        Missing dependencies are treated as blocked."""
        task = self.load_task(task_id)
        for dep_id in task.blockedBy:
            if not self._task_path(dep_id).exists():
                return False
            if self.load_task(dep_id).status != "completed":
                return False
        return True

    def claim_task(self, task_id: str, owner: str = "agent") -> str:
        """Atomically claim a pending task whose dependencies are complete."""
        with self._claim_thread_lock, _exclusive_file_lock(self._claim_lock_path):
            task = self.load_task(task_id)
            if task.status != "pending":
                return f"Task {task_id} is {task.status}, cannot claim"

            blocked_by = self._blocking_dependencies(task)
            if blocked_by:
                return f"Blocked by: {blocked_by}"

            task.owner = owner
            task.status = "in_progress"
            self.save_task(task)

        print(
            f"  \033[36m[claim] {task.subject} -> in_progress (owner: {owner})\033[0m"
        )
        return f"Claimed {task.id} ({task.subject})"

    def _blocking_dependencies(self, task: Task) -> list[str]:
        blocked_by = []
        for dependency_id in task.blockedBy:
            dependency_path = self._task_path(dependency_id)
            if not dependency_path.exists():
                blocked_by.append(dependency_id)
                continue
            if self.load_task(dependency_id).status != "completed":
                blocked_by.append(dependency_id)
        return blocked_by

    def complete_task(self, task_id: str, owner: str | None = None) -> str:
        task = self.load_task(task_id)
        if task.status == "completed":
            return f"Task {task_id} is already completed"
        if owner is not None and task.owner not in (None, owner):
            return (
                f"Task {task_id} is owned by {task.owner}, cannot complete as {owner}"
            )
        task.status = "completed"
        if owner is not None:
            task.owner = owner
        self.save_task(task)
        return f"Completed {task.id} ({task.subject})"

    def scan_unclaimed_tasks(self) -> list[Task]:
        """Return pending, unowned tasks whose dependencies are complete."""
        return [
            task
            for task in self.list_tasks()
            if (
                task.status == "pending"
                and task.owner is None
                and not self._blocking_dependencies(task)
            )
        ]

    def scan_in_progress_tasks(self, owner: str) -> list[Task]:
        """Return unfinished tasks currently owned by an agent."""
        return [
            task
            for task in self.list_tasks()
            if task.status == "in_progress" and task.owner == owner
        ]


class TaskCreateInput(BaseModel):
    subject: str = Field(..., min_length=1)
    description: str = ""
    blockedBy: list[str] = Field(default_factory=list)
    task_id: str | None = None


class TaskListInput(BaseModel):
    status: Literal["pending", "in_progress", "completed"] | None = None
    owner: str | None = None


class TaskGetInput(BaseModel):
    task_id: str


class TaskClaimInput(BaseModel):
    task_id: str
    owner: str = "agent"


class TaskCompleteInput(BaseModel):
    task_id: str
    owner: str | None = None


class ManagedTaskTool(BaseTool):
    auto_register = False

    def __init__(self, services=None):
        self.task_manager = (
            services.task_manager
            if services is not None and services.task_manager is not None
            else TaskManager()
        )


class TaskCreateTool(ManagedTaskTool):
    auto_register = True
    name = "task_create"
    description = "Create a persisted task with optional dependency task IDs."
    input_model = TaskCreateInput

    def run(self, arguments: TaskCreateInput) -> str:
        return self.task_manager.create_task(
            subject=arguments.subject,
            description=arguments.description,
            blockedBy=arguments.blockedBy,
            task_id=arguments.task_id,
        )


class TaskListTool(ManagedTaskTool):
    auto_register = True
    name = "list_tasks"
    description = "List persisted tasks, optionally filtered by status or owner."
    input_model = TaskListInput
    agent_types = {"sub_agent"}

    def run(self, arguments: TaskListInput) -> str:
        tasks = self.task_manager.list_tasks()
        if arguments.status is not None:
            tasks = [task for task in tasks if task.status == arguments.status]
        if arguments.owner is not None:
            tasks = [task for task in tasks if task.owner == arguments.owner]
        return json.dumps([asdict(task) for task in tasks], indent=2)


class TaskGetTool(ManagedTaskTool):
    auto_register = True
    name = "task_get"
    description = "Return full details for a persisted task."
    input_model = TaskGetInput

    def run(self, arguments: TaskGetInput) -> str:
        return self.task_manager.get_task(arguments.task_id)


class TaskClaimTool(ManagedTaskTool):
    auto_register = True
    name = "claim_task"
    description = "Claim a pending task if its dependencies are completed."
    input_model = TaskClaimInput
    agent_types = {"sub_agent"}

    def run(self, arguments: TaskClaimInput) -> str:
        return self.task_manager.claim_task(arguments.task_id, owner=arguments.owner)


class TaskCompleteTool(ManagedTaskTool):
    auto_register = True
    name = "complete_task"
    description = "Mark a task completed."
    input_model = TaskCompleteInput
    agent_types = {"sub_agent"}

    def run(self, arguments: TaskCompleteInput) -> str:
        return self.task_manager.complete_task(
            arguments.task_id,
            owner=arguments.owner,
        )
