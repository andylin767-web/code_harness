import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4


def run_teammate_session(
    lead_agent,
    sub_agent,
    parent_conversation_id: str,
    message_bus,
):
    """Run one teammate lifecycle, including inbox and shared-task polling."""
    from code_harness.core.agent import handle_inbox_messages, idle_poll
    from code_harness.core.loop import Loop, LoopStatus
    from code_harness.core.permissions import PermissionEngine
    from code_harness.core.tracing import save_trace, utc_now_iso
    from code_harness.memory.context import ConversationStore, MessageRecord
    from code_harness.team.message_type import MessageType
    from code_harness.team.protocol_dispatcher import ProtocolDispatcher
    from code_harness.team.protocol_manager import ProtocolManager
    from code_harness.team.send import Sender
    from code_harness.tools.task_system import TaskManager

    conversation_id = f"conv_{uuid4().hex}"
    store = ConversationStore()
    started_at = utc_now_iso()
    run_id = f"{started_at.replace(':', '-').replace('+', 'Z')}_{uuid4().hex[:8]}"
    permission_engine = PermissionEngine(workspace_root=sub_agent.workspace_root)
    settings_path = _settings_path(lead_agent)
    if settings_path is None:
        permission_engine.load_settings_json()
    else:
        permission_engine.load_settings_json(settings_path)
    loop_options: dict[str, Any] = {"max_runs": 10}
    if lead_agent.services is not None:
        loop_options["input_broker"] = lead_agent.services.input_broker
    loop = Loop(sub_agent, permission_engine, **loop_options)
    dispatcher = ProtocolDispatcher(
        sender=Sender(message_bus),
        protocol_manager=(
            lead_agent.services.protocol_manager
            if lead_agent.services is not None
            else ProtocolManager()
        ),
    )
    task_manager = (
        lead_agent.services.task_manager
        if lead_agent.services is not None
        else TaskManager(_task_dir(lead_agent))
    )
    store.append_record(
        MessageRecord.system(
            conversation_id=conversation_id,
            content=loop.system_prompt,
        )
    )

    async def run_session():
        next_user_message = sub_agent.assignment
        inbox = message_bus.read_inbox(sub_agent.name)
        last_result = None
        exit_status = "timeout"
        exit_detail = ""

        while True:
            messages: list[dict] = []
            if handle_inbox_messages(
                sub_agent.name,
                inbox,
                messages,
                dispatcher,
            ):
                exit_status = "shutdown"
                break
            injected = [
                str(message["content"])
                for message in messages
                if message.get("content")
            ]
            if injected:
                next_user_message = "\n\n".join(
                    [next_user_message, *injected] if next_user_message else injected
                )

            result = await loop.run(store, conversation_id, next_user_message)
            last_result = result
            if result.status not in {LoopStatus.COMPLETED, LoopStatus.MAX_RUNS}:
                exit_status = str(result.status)
                break

            idle_messages: list[dict[str, Any]] = []
            idle_status = await idle_poll(
                sub_agent.name,
                idle_messages,
                sub_agent.role,
                message_bus=message_bus,
                teammate_dispatcher=dispatcher,
                task_manager=task_manager,
                on_task_selected=lambda task: lead_agent._activate_task_workspace(
                    sub_agent,
                    permission_engine,
                    task,
                    (
                        lead_agent.services.worktree_manager
                        if lead_agent.services is not None
                        else None
                    ),
                ),
                timeout_seconds=lead_agent.teammate_idle_timeout,
                poll_interval=lead_agent.teammate_inbox_poll_interval,
            )
            if idle_status != "work":
                exit_status = idle_status
                if idle_status == "workspace_error" and idle_messages:
                    exit_detail = str(idle_messages[0].get("content", ""))
                break
            next_user_message = "\n\n".join(
                str(message["content"])
                for message in idle_messages
                if message.get("content")
            )
            inbox = []

        summary = (
            exit_detail
            if exit_detail
            else (
                last_result.summary
                if last_result is not None
                else f"Teammate stopped: {exit_status}"
            )
        )
        message_bus.send(
            from_agent=sub_agent.name,
            to_agent="lead",
            content=summary,
            msg_type=MessageType.RESULT,
            metadata={"exit_status": exit_status},
        )
        if last_result is not None and last_result.status != LoopStatus.COMPLETED:
            return last_result
        return None

    try:
        return asyncio.run(run_session())
    finally:
        save_trace(
            run_id=run_id,
            started_at=started_at,
            ended_at=utc_now_iso(),
            user_input=sub_agent.assignment,
            conversation_id=conversation_id,
            parent_conversation_id=parent_conversation_id,
            messages=store.get_records_by_conversation_id(conversation_id),
            trace_type="subagent",
            trace_dir=_trace_dir(lead_agent),
        )


def _settings_path(lead_agent) -> Path | None:
    if lead_agent.services is None:
        return None
    return getattr(lead_agent.services, "settings_path", None)


def _task_dir(lead_agent) -> Path | None:
    if lead_agent.services is None:
        return None
    return lead_agent.services.state_root / ".tasks"


def _trace_dir(lead_agent) -> Path | None:
    if lead_agent.services is None:
        return None
    return lead_agent.services.state_root / "traces"
