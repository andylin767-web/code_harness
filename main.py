import asyncio
import os
import threading
from pathlib import Path
from uuid import uuid4

import litellm

from code_harness.core.agent import LeadAgent
from code_harness.core.agent_runtime import set_lead_agent
from code_harness.core.config import get_model_id
from code_harness.core.input_broker import InputBroker
from code_harness.core.input_runtime import set_input_broker
from code_harness.core.llm_client import LLMClient
from code_harness.core.loop import Loop
from code_harness.core.permissions import PROJECT_ROOT, PermissionEngine
from code_harness.core.tracing import save_trace, utc_now_iso
from code_harness.cron_scheduler.runtime import set_cron_scheduler
from code_harness.cron_scheduler.scheduler import (
    CronScheduler,
    start_cron_scheduler_daemon,
)
from code_harness.events.models import EventType, new_event
from code_harness.events.processor import QueueProcessor
from code_harness.events.queue import EventQueue
from code_harness.events.runtime import set_event_queue
from code_harness.goals.command import GoalCommandHandler
from code_harness.goals.context import GoalContextBuilder
from code_harness.goals.controller import GoalController
from code_harness.goals.evaluator import PromptGoalEvaluator
from code_harness.mcp.registry import MCPRegistry, configured_mcp_servers
from code_harness.memory.context import ConversationStore, MessageRecord
from code_harness.team.lead_inbox import LeadInbox, set_lead_inbox
from code_harness.team.message_bus import MessageBus
from code_harness.tools.tools import get_tools
from code_harness.ui_config import console

litellm.api_key = os.getenv("OPENROUTER_API_KEY")


async def main():

    model_id = get_model_id()
    workspace = Path.cwd() / "code_harness"
    workspace.mkdir(exist_ok=True)
    Path(workspace / "test_workspace").mkdir(exist_ok=True)

    SYSTEM_PROMPT = f"""You are a coding agent at {workspace} and {Path(workspace / "test_workspace")},
            Tool use policy:
            - Prefer tools when they help complete the user's request.
            - Do not call every available tool.
            - Use the smallest number of tool calls needed.
            - For multi-step implementation tasks, use the todo tool:
            - create a todo list before starting,
            - mark the current task in_progress,
            - mark tasks completed as they are finished.
            - Do not inspect .venv when working with Python files.
            """
    conversation_id = f"conv_{uuid4().hex}"
    conversation_store = ConversationStore()
    tool_registry = get_tools("parent")
    mcp_registry = MCPRegistry()
    mcp_servers = configured_mcp_servers(PROJECT_ROOT / "settings.json")
    for message in await mcp_registry.connect_many(mcp_servers, tool_registry):
        console.print(f"[dim]{message}[/dim]")
    permission_engine = PermissionEngine()
    permission_engine.load_settings_json()
    agent = LeadAgent(
        name="Main agent",
        role="coding agent",
        assignment="Complete the user's coding tasks in the code_harness workspace.",
        toolset=tool_registry,
        system_prompt=SYSTEM_PROMPT,
        model=model_id,
    )
    set_lead_agent(agent)
    event_queue = EventQueue(workspace)
    set_event_queue(event_queue)
    set_lead_inbox(LeadInbox(MessageBus(PROJECT_ROOT / ".mailboxes")))
    goal_evaluator = PromptGoalEvaluator(
        client=LLMClient(),
        model=os.getenv("GOAL_EVALUATOR_MODEL_ID") or agent.model,
    )

    goal_controller = GoalController(
        evaluator=goal_evaluator,
        context_builder=GoalContextBuilder(),
    )

    goal_command_handler = GoalCommandHandler(goal_controller)
    input_broker = InputBroker(
        output_fn=lambda message: console.print(message, end=" "),
        flush_fn=console.file.flush,
    )
    set_input_broker(input_broker)
    loop = Loop(
        agent,
        permission_engine,
        event_queue=event_queue,
        goal_controller=goal_controller,
    )
    conversation_store.append_record(
        MessageRecord.system(
            conversation_id=conversation_id, content=loop.system_prompt
        )
    )
    run_lock = threading.Lock()
    event_queue.load_events()
    scheduler = CronScheduler(workspace, event_queue)
    set_cron_scheduler(scheduler)
    scheduler.load_durable_jobs()
    start_cron_scheduler_daemon(scheduler)
    queue_processor = QueueProcessor(
        event_queue=event_queue,
        loop=loop,
        conversation_store=conversation_store,
        conversation_id=conversation_id,
        run_lock=run_lock,
        poll_interval=0.1,
        trace_saver=save_trace,
    )
    queue_processor.start()
    input_broker.start()

    while True:
        should_quit = False
        user_input = await asyncio.to_thread(input_broker.get_user_input)
        if user_input is None:
            user_input = ""
            should_quit = True

        if not user_input and not should_quit:
            continue

        if user_input.lower() in ("exit", "quit"):
            should_quit = True

        if should_quit:
            quit_event = new_event(
                EventType.QUIT,
                "quit",
                source="terminal",
                created_at=utc_now_iso(),
            )
            await asyncio.wrap_future(event_queue.submit(quit_event))
            console.print("\n[dim]Goodbye.[/dim]")
            break
        goal_command = goal_command_handler.handle(
            user_input,
            conversation_id=conversation_id,
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
        run_id = started_at.replace(":", "-").replace("+", "Z")
        event = new_event(
            EventType.USER,
            user_input,
            source="terminal",
            created_at=started_at,
            metadata={"run_id": run_id},
        )
        await asyncio.wrap_future(event_queue.submit(event))

    queue_processor.stop()
    input_broker.stop()
    set_input_broker(None)
    await mcp_registry.close(tool_registry)


if __name__ == "__main__":
    asyncio.run(main())
