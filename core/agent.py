import asyncio
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from code_harness.core.permissions import PROJECT_ROOT

if TYPE_CHECKING:
    from code_harness.core.loop import LoopResult
    from code_harness.team.message_bus import MessageBus
    from code_harness.team.protocol_dispatcher import ProtocolDispatcher
    from code_harness.tools.task_system import TaskManager


def handle_inbox_messages(
    name: str,
    inbox: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    teammate_dispatcher: "ProtocolDispatcher",
) -> bool:
    """Dispatch inbox messages, always handling shutdown first."""
    shutdown_messages = [
        message for message in inbox if message.get("type") == "shutdown_request"
    ]
    for message in shutdown_messages:
        if teammate_dispatcher.dispatch(name, message, messages):
            return True

    for message in inbox:
        if message.get("type") == "shutdown_request":
            continue
        if teammate_dispatcher.dispatch(name, message, messages):
            return True
    return False


def resolve_task_workspace(task: Any, worktree_manager=None) -> Path:
    """Resolve a task's worktree, failing closed when it is unavailable."""
    if worktree_manager is None:
        from code_harness.core.worktrees import manager as worktree_manager

    if not task.worktree:
        return worktree_manager.repo_root

    path = worktree_manager.worktree_path(task.worktree)
    if not path.is_dir() or not (path / ".git").exists():
        raise FileNotFoundError(
            f"Task {task.id} references unavailable worktree "
            f"'{task.worktree}' at {path}. Recreate or rebind the worktree."
        )
    return path.resolve()


def _task_work_message(
    task: Any,
    name: str,
    *,
    workspace_root: Path = PROJECT_ROOT,
    resumed: bool = False,
) -> str:
    action = "Continue" if resumed else "Complete"
    state = "already own" if resumed else "claimed"
    return (
        f"You {state} a task from the shared task board.\n"
        f"Task ID: {task.id}\n"
        f"Subject: {task.subject}\n"
        f"Description: {task.description}\n"
        f"Active workspace: {workspace_root}\n\n"
        f"{action} this task now. When the work is finished, call "
        "complete_task with this task ID and your name "
        f"({name}) as owner."
    )


async def idle_poll(
    name: str,
    messages: list[dict[str, Any]],
    role: str,
    *,
    message_bus: "MessageBus",
    teammate_dispatcher: "ProtocolDispatcher",
    task_manager: "TaskManager",
    on_task_selected: Callable[[Any], Path] | None = None,
    timeout_seconds: float = 60.0,
    poll_interval: float = 5.0,
) -> str:
    """Poll inbox first, then the task board, until work or shutdown."""
    del role  # Reserved for future role-aware task selection.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    while loop.time() < deadline:
        await asyncio.sleep(poll_interval)

        inbox = message_bus.read_inbox(name)
        if inbox:
            if handle_inbox_messages(
                name,
                inbox,
                messages,
                teammate_dispatcher,
            ):
                return "shutdown"
            return "work"

        owned_tasks = task_manager.scan_in_progress_tasks(owner=name)
        if owned_tasks:
            task = owned_tasks[0]
            try:
                workspace_root = (
                    on_task_selected(task)
                    if on_task_selected is not None
                    else PROJECT_ROOT
                )
            except Exception as exc:
                messages.append({"role": "user", "content": str(exc)})
                return "workspace_error"
            messages.append(
                {
                    "role": "user",
                    "content": _task_work_message(
                        task,
                        name,
                        workspace_root=workspace_root,
                        resumed=True,
                    ),
                }
            )
            return "work"

        for task in task_manager.scan_unclaimed_tasks():
            result = task_manager.claim_task(task.id, owner=name)
            if result.startswith("Claimed"):
                try:
                    workspace_root = (
                        on_task_selected(task)
                        if on_task_selected is not None
                        else PROJECT_ROOT
                    )
                except Exception as exc:
                    messages.append({"role": "user", "content": str(exc)})
                    return "workspace_error"
                messages.append(
                    {
                        "role": "user",
                        "content": _task_work_message(
                            task,
                            name,
                            workspace_root=workspace_root,
                        ),
                    }
                )
                return "work"

    return "timeout"


@dataclass
class Agent:
    name: str
    role: str
    assignment: str
    toolset: Any
    system_prompt: str
    model: str
    workspace_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    services: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.set_workspace_root(self.workspace_root)

    def set_workspace_root(self, path: Path) -> None:
        self.workspace_root = Path(path).expanduser().resolve()

    @property
    def tool_registry(self) -> Any:
        return self.toolset

    def build_system_prompt(self) -> str:
        return "\n\n".join(
            part.strip()
            for part in [
                f"Agent name: {self.name}",
                f"Role: {self.role}",
                f"Assignment: {self.assignment}",
                f"Active workspace: {self.workspace_root}",
                self.system_prompt,
            ]
            if part
        )


@dataclass
class LeadAgent(Agent):
    subagents: list[Agent] = field(default_factory=list)
    teammate_specs: dict[str, dict[str, str]] = field(
        default_factory=dict,
        repr=False,
    )
    _teammate_lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )
    teammate_inbox_poll_interval: float = field(
        default=5.0,
        repr=False,
    )
    teammate_idle_timeout: float = field(
        default=60.0,
        repr=False,
    )

    def add_subagent(self, agent: Agent) -> None:
        self.subagents.append(agent)

    def remove_subagent(self, agent: Agent) -> None:
        if agent in self.subagents:
            self.subagents.remove(agent)

    @staticmethod
    def _activate_task_workspace(
        agent: Agent,
        permission_engine: Any,
        task: Any,
        worktree_manager=None,
    ) -> Path:
        workspace_root = resolve_task_workspace(task, worktree_manager)
        agent.set_workspace_root(workspace_root)
        permission_engine.set_workspace_root(workspace_root)
        return workspace_root

    def _run_sub_agent(
        self,
        sub_agent: Agent,
        parent_conversation_id: str,
        message_bus: "MessageBus",
    ) -> "LoopResult | None":
        from code_harness.team.teammate_runner import run_teammate_session

        return run_teammate_session(
            self,
            sub_agent,
            parent_conversation_id,
            message_bus,
        )

    def spawn_teammate_thread(
        self,
        name: str,
        role: str,
        assignment: str,
        parent_conversation_id: str,
    ) -> str:
        from code_harness.core.permissions import PROJECT_ROOT
        from code_harness.team.message_bus import MessageBus
        from code_harness.tools.tools import get_tools

        tool_registry = get_tools("sub_agent", services=self.services)
        system_prompt = (
            f"You are {name}, a {role}. Complete your assigned task using tools. "
            "Send important updates and final results to the lead."
        )

        sub_agent = Agent(
            name=name,
            role=role,
            assignment=assignment,
            toolset=tool_registry,
            system_prompt=system_prompt,
            model=self.model,
            workspace_root=self.workspace_root,
            services=self.services,
        )

        if self.services is not None:
            message_bus = self.services.message_bus
        else:
            mailbox_dir = PROJECT_ROOT / ".mailboxes"
            mailbox_dir.mkdir(exist_ok=True)
            message_bus = MessageBus(mailbox_dir)
        with self._teammate_lock:
            if any(agent.name == name for agent in self.subagents):
                return f"Teammate '{name}' already exists"
            self.teammate_specs[name] = {
                "role": role,
                "parent_conversation_id": parent_conversation_id,
            }
            self.add_subagent(sub_agent)

        def worker() -> None:
            try:
                current_agent = sub_agent
                while True:
                    result = self._run_sub_agent(
                        sub_agent=current_agent,
                        parent_conversation_id=parent_conversation_id,
                        message_bus=message_bus,
                    )
                    if result is None:
                        return
                    with self._teammate_lock:
                        if not message_bus.peek(name):
                            self.remove_subagent(sub_agent)
                            return
                        current_agent = Agent(
                            name=name,
                            role=role,
                            assignment="Handle the queued follow-up messages.",
                            toolset=tool_registry,
                            system_prompt=system_prompt,
                            model=current_agent.model,
                            workspace_root=current_agent.workspace_root,
                            services=self.services,
                        )
            except Exception as exc:
                message_bus.send(
                    from_agent=name,
                    to_agent="lead",
                    content=f"Failed: {type(exc).__name__}: {exc}",
                    msg_type="error",
                )
            finally:
                with self._teammate_lock:
                    self.remove_subagent(sub_agent)

        thread = threading.Thread(
            target=worker,
            daemon=True,
            name=f"teammate-{name}",
        )
        thread.start()

        return f"Teammate '{name}' spawned as {role}"

    def send_teammate_message(self, name: str, content: str) -> str:
        """Deliver now if active, or recreate a completed teammate on demand."""
        from code_harness.core.permissions import PROJECT_ROOT
        from code_harness.team.message_bus import MessageBus

        with self._teammate_lock:
            spec = self.teammate_specs.get(name)
            if spec is None:
                return f"No teammate found: {name}"

            if any(agent.name == name for agent in self.subagents):
                if self.services is not None:
                    message_bus = self.services.message_bus
                else:
                    mailbox_dir = PROJECT_ROOT / ".mailboxes"
                    mailbox_dir.mkdir(exist_ok=True)
                    message_bus = MessageBus(mailbox_dir)
                message_bus.send(
                    from_agent="lead",
                    to_agent=name,
                    content=content,
                )
                return f"Sent message to {name}"

            role = spec["role"]
            parent_conversation_id = spec["parent_conversation_id"]

        self.spawn_teammate_thread(
            name=name,
            role=role,
            assignment=content,
            parent_conversation_id=parent_conversation_id,
        )
        return f"Restarted teammate {name} with follow-up message"
