import asyncio
import os
import signal
import threading
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from uuid import uuid4

from code_harness.core.agent import LeadAgent
from code_harness.core.config import get_model_id
from code_harness.core.input_broker import InputBroker
from code_harness.core.llm_client import LLMClient
from code_harness.core.loop import Loop
from code_harness.core.permissions import PROJECT_ROOT, PermissionEngine
from code_harness.core.services import RuntimeServices
from code_harness.core.tracing import record_goal_stage, save_trace, utc_now_iso
from code_harness.core.worktrees import WorktreeManager
from code_harness.cron_scheduler.scheduler import CronScheduler
from code_harness.events.models import EventType, new_event
from code_harness.events.processor import QueueProcessor
from code_harness.events.queue import EventQueue
from code_harness.goals.command import GoalCommandHandler
from code_harness.goals.context import GoalContextBuilder
from code_harness.goals.controller import GoalController
from code_harness.goals.evaluator import PromptGoalEvaluator
from code_harness.mcp.registry import MCPRegistry, configured_mcp_servers
from code_harness.memory.context import ConversationStore, MessageRecord
from code_harness.team.lead_inbox import LeadInbox
from code_harness.team.message_bus import MessageBus
from code_harness.team.protocol_manager import ProtocolManager
from code_harness.tools.task_system import TaskManager
from code_harness.tools.tools import ToolRegistry, get_tools
from code_harness.ui_config import console


@dataclass(frozen=True)
class ApplicationConfig:
    """Filesystem and model-independent settings for one harness process."""

    workspace_root: Path
    state_root: Path = PROJECT_ROOT
    settings_path: Path = PROJECT_ROOT / "settings.json"

    def resolved(self) -> "ApplicationConfig":
        return ApplicationConfig(
            workspace_root=self.workspace_root.expanduser().resolve(),
            state_root=self.state_root.expanduser().resolve(),
            settings_path=self.settings_path.expanduser().resolve(),
        )


class HarnessApplication:
    """Own all long-lived runtime services and their shutdown order."""

    def __init__(
        self,
        *,
        config: ApplicationConfig,
        conversation_id: str,
        conversation_store: ConversationStore,
        tool_registry: ToolRegistry,
        mcp_registry: MCPRegistry,
        input_broker: InputBroker,
        event_queue: EventQueue,
        queue_processor: QueueProcessor,
        scheduler: CronScheduler,
        goal_command_handler: GoalCommandHandler,
    ) -> None:
        self.config = config
        self.conversation_id = conversation_id
        self.conversation_store = conversation_store
        self.tool_registry = tool_registry
        self.mcp_registry = mcp_registry
        self.input_broker = input_broker
        self.event_queue = event_queue
        self.queue_processor = queue_processor
        self.scheduler = scheduler
        self.goal_command_handler = goal_command_handler
        self._started = False
        self._closed = False

    @classmethod
    async def create(
        cls,
        config: ApplicationConfig,
        *,
        input_broker: InputBroker | None = None,
        mcp_registry: MCPRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> "HarnessApplication":
        config = config.resolved()
        if not config.workspace_root.is_dir():
            raise FileNotFoundError(
                f"Workspace does not exist: {config.workspace_root}"
            )
        config.state_root.mkdir(parents=True, exist_ok=True)

        import litellm

        model_id = get_model_id()
        litellm.api_key = os.getenv("OPENROUTER_API_KEY")
        conversation_id = f"conv_{uuid4().hex}"
        conversation_store = ConversationStore()

        input_broker = input_broker or InputBroker(
            output_fn=lambda message: console.print(message, end=" "),
            flush_fn=console.file.flush,
        )
        event_queue = EventQueue(config.state_root)
        scheduler = CronScheduler(config.state_root, event_queue)
        message_bus = MessageBus(config.state_root / ".mailboxes", event_queue)
        protocol_manager = ProtocolManager(
            config.state_root / ".protocol_requests.json"
        )
        lead_inbox = LeadInbox(
            message_bus,
            response_matcher=protocol_manager.process_response,
        )
        task_manager = TaskManager(config.state_root / ".tasks")
        worktree_manager = WorktreeManager(
            repo_root=config.workspace_root,
            worktrees_dir=config.state_root / ".worktrees",
            task_manager=task_manager,
        )
        services = RuntimeServices(
            state_root=config.state_root,
            event_queue=event_queue,
            input_broker=input_broker,
            scheduler=scheduler,
            message_bus=message_bus,
            protocol_manager=protocol_manager,
            settings_path=config.settings_path,
            task_manager=task_manager,
            worktree_manager=worktree_manager,
            lead_inbox=lead_inbox,
        )
        tool_registry = tool_registry or get_tools("parent", services=services)
        mcp_servers = configured_mcp_servers(config.settings_path)
        mcp_registry = mcp_registry or MCPRegistry.from_settings(config.settings_path)
        for message in await mcp_registry.connect_many(mcp_servers, tool_registry):
            console.print(f"[dim]{message}[/dim]")

        permission_engine = PermissionEngine(workspace_root=config.workspace_root)
        permission_engine.load_settings_json(config.settings_path)
        system_prompt = _system_prompt(config.workspace_root)
        agent = LeadAgent(
            name="Main agent",
            role="coding agent",
            assignment="Complete the user's coding tasks in the active workspace.",
            toolset=tool_registry,
            system_prompt=system_prompt,
            model=model_id,
            workspace_root=config.workspace_root,
            services=services,
        )
        services.lead_agent = agent
        goal_evaluator = PromptGoalEvaluator(
            client=LLMClient(),
            model=os.getenv("GOAL_EVALUATOR_MODEL_ID") or agent.model,
        )
        goal_controller = GoalController(
            evaluator=goal_evaluator,
            context_builder=GoalContextBuilder(),
            trace_recorder=partial(
                record_goal_stage,
                trace_dir=config.state_root / "traces",
            ),
        )
        loop = Loop(
            agent,
            permission_engine,
            event_queue=event_queue,
            goal_controller=goal_controller,
            input_broker=input_broker,
            trace_recorder=partial(
                record_goal_stage,
                trace_dir=config.state_root / "traces",
            ),
        )
        conversation_store.append_record(
            MessageRecord.system(
                conversation_id=conversation_id,
                content=loop.system_prompt,
            )
        )
        queue_processor = QueueProcessor(
            event_queue=event_queue,
            loop=loop,
            conversation_store=conversation_store,
            conversation_id=conversation_id,
            run_lock=threading.Lock(),
            poll_interval=0.1,
            lead_inbox_consumer=lead_inbox.consume,
            trace_saver=lambda **kwargs: save_trace(
                **kwargs,
                trace_dir=config.state_root / "traces",
            ),
            input_broker=input_broker,
        )

        return cls(
            config=config,
            conversation_id=conversation_id,
            conversation_store=conversation_store,
            tool_registry=tool_registry,
            mcp_registry=mcp_registry,
            input_broker=input_broker,
            event_queue=event_queue,
            queue_processor=queue_processor,
            scheduler=scheduler,
            goal_command_handler=GoalCommandHandler(goal_controller),
        )

    def start(self) -> None:
        if self._started:
            return
        self.event_queue.load_events()
        self.scheduler.load_durable_jobs()
        self.scheduler.start()
        self.queue_processor.start()
        self.input_broker.start()
        self._started = True

    def request_stop(self) -> None:
        self.input_broker.stop()

    async def run_interactive(self) -> None:
        self.start()
        while True:
            user_input = await asyncio.to_thread(self.input_broker.get_user_input)
            if user_input is None or user_input.lower() in {"exit", "quit"}:
                await self._submit_quit()
                console.print("\n[dim]Goodbye.[/dim]")
                return
            if not user_input:
                continue

            goal_command = self.goal_command_handler.handle(
                user_input,
                conversation_id=self.conversation_id,
                current_tokens=0,
            )
            if goal_command.handled:
                if goal_command.output:
                    console.print(goal_command.output)
                if not goal_command.starts_work:
                    continue
                assert goal_command.work_request is not None
                user_input = goal_command.work_request

            started_at = utc_now_iso()
            event = new_event(
                EventType.USER,
                user_input,
                source="terminal",
                created_at=started_at,
                metadata={"run_id": started_at.replace(":", "-").replace("+", "Z")},
            )
            await asyncio.wrap_future(self.event_queue.submit(event))

    async def _submit_quit(self) -> None:
        if not self._started:
            return
        event = new_event(
            EventType.QUIT,
            "quit",
            source="terminal",
            created_at=utc_now_iso(),
        )
        await asyncio.wrap_future(self.event_queue.submit(event))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.input_broker.stop()
        self.scheduler.stop()
        self.queue_processor.stop()
        await self.mcp_registry.close(self.tool_registry)

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, self.request_stop)
            except (NotImplementedError, RuntimeError):
                continue


def _system_prompt(workspace_root: Path) -> str:
    return f"""You are a coding agent working in {workspace_root}.

Tool use policy:
- Prefer tools when they help complete the user's request.
- Use the smallest number of tool calls needed.
- For multi-step implementation tasks, keep the todo list current.
- Do not inspect .venv when working with Python files.
"""


async def run_application(
    workspace_root: Path,
    *,
    state_root: Path = PROJECT_ROOT,
    settings_path: Path = PROJECT_ROOT / "settings.json",
    input_broker: InputBroker | None = None,
    mcp_registry: MCPRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> None:
    application = await HarnessApplication.create(
        ApplicationConfig(workspace_root, state_root, settings_path),
        input_broker=input_broker,
        mcp_registry=mcp_registry,
        tool_registry=tool_registry,
    )
    application.install_signal_handlers()
    try:
        await application.run_interactive()
    finally:
        await application.close()
