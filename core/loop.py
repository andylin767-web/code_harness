from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from code_harness.core.agent import Agent
from code_harness.core.background_task import BackgroundTaskRunner
from code_harness.core.input_runtime import get_input_broker
from code_harness.core.llm_client import LLMClient
from code_harness.core.permissions import (
    PermissionDecision,
    PermissionEngine,
    PermissionOutcome,
    Rule,
)
from code_harness.core.tracing import record_goal_stage
from code_harness.events.models import EventType, new_event
from code_harness.events.queue import EventQueue
from code_harness.goals.models import StopAction
from code_harness.memory.context import ContextBuilder, MessageRecord
from code_harness.tools.skill_loader import DEFAULT_SKILL_DIRS, SkillLoader
from code_harness.tools.tools import run_tool

if TYPE_CHECKING:
    from code_harness.goals.controller import GoalController


@dataclass
class LoopResult:
    status: str
    runs: int
    tool_calls: int
    summary: str


@dataclass
class _RunState:
    runs: int = 0
    tool_calls: int = 0
    rounds_since_todo: int = 0
    allow_all_actions: bool = False


class LoopStatus(StrEnum):
    COMPLETED = "completed"
    MAX_RUNS = "max_runs"
    MAX_TOOL_CALLS = "max_tool_calls"
    DENIED = "denied"
    ERROR = "error"
    GOAL_DEFERRED = "goal_deferred"
    GOAL_IMPOSSIBLE = "goal_impossible"
    GOAL_PAUSED = "goal_paused"
    GOAL_EVALUATION_ERROR = "goal_evaluation_error"


class Loop:
    def __init__(
        self,
        agent: Agent,
        permission_engine: PermissionEngine,
        max_runs: int = 20,
        max_tool_calls: int = 100,
        max_run: int | None = None,
        event_queue: EventQueue | None = None,
        goal_controller: GoalController | None = None,
    ):
        if max_run is not None:
            max_runs = max_run
        self.agent = agent
        self.model = agent.model
        self.max_runs = max_runs
        self.max_tool_calls = max_tool_calls
        self.event_queue = event_queue

        self.permission_engine = permission_engine
        self.context_Builder = ContextBuilder()
        self.skill_loader = SkillLoader(DEFAULT_SKILL_DIRS)
        self.goal_controller = goal_controller
        self.system_prompt = (
            agent.build_system_prompt()
            + f"""
                You have access to these skills:

                {self.skill_loader.list_skills_for_prompt()}

                When the user's request matches a skill, use that skill's instructions.
                If multiple skills apply, use the smallest set needed.
                If no skill applies, answer normally.
            """
        )

        print(f"system prompt: {self.system_prompt}")

    def _subagent_run_budget(self, total_run: int) -> int:
        return max(0, self.max_runs - total_run - 1)

    def _subagent_tool_call_budget(self, total_tool_call: int) -> int:
        remaining_tool_calls = max(0, self.max_tool_calls - total_tool_call)
        return remaining_tool_calls // 2

    async def _execute_tool_call(self, tc, tool_registry, workspace_root):
        tool = tool_registry.get(tc.function.name)
        return await run_tool(tool, tc, workspace_root=workspace_root)

    def _append_background_notifications(
        self, background_runner, conversation_store, conversation_id
    ) -> int:
        notification_count = 0
        for notification in background_runner.collect_completed():
            conversation_store.append_record(
                MessageRecord.user(
                    conversation_id=conversation_id,
                    content=notification,
                )
            )
            notification_count += 1
        return notification_count

    async def _wait_for_background_tasks(
        self, background_runner, conversation_store, conversation_id
    ) -> None:
        while background_runner.has_pending():
            self._append_background_notifications(
                background_runner, conversation_store, conversation_id
            )
            if not background_runner.has_pending():
                return
            await asyncio.sleep(0.1)

    async def run(
        self,
        conversation_store,
        conversation_id,
        user_message,
        *,
        event_id: str | None = None,
        event_type: str | None = None,
        run_id: str | None = None,
    ):
        workspace_root = self.agent.workspace_root
        self.permission_engine.set_workspace_root(workspace_root)
        state = _RunState()
        llm_client = LLMClient()
        tool_registry = self.agent.toolset
        trace_context = self._goal_trace_context(
            conversation_id=conversation_id,
            event_id=event_id,
            run_id=run_id,
        )
        self._trace_goal_stage(
            trace_context,
            "worker_started",
            details={"event_type": event_type, "worker_model": self.model},
        )
        background_runner = self._create_background_runner(
            tool_registry,
            workspace_root,
            trace_context,
        )

        conversation_store.append_record(
            MessageRecord.user(
                conversation_id=conversation_id,
                content=user_message,
            )
        )

        while state.runs < self.max_runs:
            self._append_background_notifications(
                background_runner,
                conversation_store,
                conversation_id,
            )
            message = await self._next_assistant_message(
                llm_client,
                tool_registry,
                conversation_store,
                conversation_id,
            )

            if not message.tool_calls:
                result = await self._handle_stop_proposal(
                    message=message,
                    state=state,
                    background_runner=background_runner,
                    conversation_store=conversation_store,
                    conversation_id=conversation_id,
                    trace_context=trace_context,
                )
                if result is None:
                    continue
                return result

            result, saw_todo = await self._process_tool_calls(
                tool_calls=message.tool_calls,
                state=state,
                tool_registry=tool_registry,
                background_runner=background_runner,
                conversation_store=conversation_store,
                conversation_id=conversation_id,
                workspace_root=workspace_root,
                trace_context=trace_context,
            )
            if result is not None:
                return result

            self._update_todo_reminder(
                state,
                saw_todo=saw_todo,
                conversation_store=conversation_store,
                conversation_id=conversation_id,
            )
            state.runs += 1

        message = f"exceed max run {self.max_runs}"
        conversation_store.append_record(
            MessageRecord.developer(
                conversation_id=conversation_id,
                content=message,
            )
        )
        return self._result(LoopStatus.MAX_RUNS, state, message)

    def _create_background_runner(
        self,
        tool_registry,
        workspace_root,
        trace_context=None,
    ):
        on_complete = None
        if self.event_queue is not None:

            def enqueue_notification(notification):
                self._enqueue_background_notification(
                    notification,
                    trace_context=trace_context,
                )

            on_complete = enqueue_notification

        return BackgroundTaskRunner(
            executor=lambda tc: self._execute_tool_call(
                tc,
                tool_registry,
                workspace_root,
            ),
            on_complete=on_complete,
        )

    def _enqueue_background_notification(
        self,
        notification: str,
        *,
        trace_context=None,
    ) -> None:
        if self.event_queue is None:
            return
        background_task_id = self._notification_tag(notification, "task_id")
        self._trace_goal_stage(
            trace_context,
            "background_completed",
            background_task_id=background_task_id,
            details={
                "status": self._notification_tag(notification, "status"),
                "command": self._notification_tag(notification, "command"),
                "exit_code": self._background_exit_code(notification),
                "notification": notification,
            },
        )
        metadata = {
            key: value
            for key, value in {
                "goal_id": (trace_context or {}).get("goal_id"),
                "parent_event_id": (trace_context or {}).get("event_id"),
                "parent_run_id": (trace_context or {}).get("run_id"),
                "background_task_id": background_task_id,
            }.items()
            if value is not None
        }
        self.event_queue.put(
            new_event(
                EventType.BACKGROUND_TASK,
                notification,
                source="background-task",
                created_at=datetime.now(UTC).isoformat(),
                metadata=metadata,
            )
        )

    async def _next_assistant_message(
        self,
        llm_client,
        tool_registry,
        conversation_store,
        conversation_id,
    ):
        messages = await self.context_Builder.build(
            conversation_store,
            conversation_id,
        )
        response = await llm_client.send(
            self.model,
            messages,
            tool_registry.schemas(),
        )
        message = response.choices[0].message
        conversation_store.append_record(
            MessageRecord.assistant(
                conversation_id=conversation_id,
                content=message.model_dump(),
            )
        )
        return message

    async def _handle_stop_proposal(
        self,
        *,
        message,
        state: _RunState,
        background_runner,
        conversation_store,
        conversation_id,
        trace_context,
    ) -> LoopResult | None:
        if self.event_queue is None and background_runner.has_pending():
            await self._wait_for_background_tasks(
                background_runner,
                conversation_store,
                conversation_id,
            )
            return None

        if self.goal_controller is None:
            return self._result(
                LoopStatus.COMPLETED,
                state,
                message.content or "",
            )

        decision = await self.goal_controller.evaluate_after_turn(
            store=conversation_store,
            conversation_id=conversation_id,
            background_pending=background_runner.has_pending(),
            event_id=(trace_context or {}).get("event_id"),
            run_id=(trace_context or {}).get("run_id"),
        )
        if decision.action is StopAction.BLOCK:
            conversation_store.append_record(
                MessageRecord.user(
                    conversation_id=conversation_id,
                    content=(f"<goal_feedback>\n{decision.reason}\n</goal_feedback>"),
                )
            )
            state.runs += 1
            return None

        status_by_action = {
            StopAction.DEFER: LoopStatus.GOAL_DEFERRED,
            StopAction.IMPOSSIBLE: LoopStatus.GOAL_IMPOSSIBLE,
            StopAction.PAUSE: LoopStatus.GOAL_PAUSED,
            StopAction.ERROR: LoopStatus.GOAL_EVALUATION_ERROR,
        }
        status = status_by_action.get(decision.action)
        if status is not None:
            return self._result(status, state, decision.reason)

        return self._result(
            LoopStatus.COMPLETED,
            state,
            message.content or "",
        )

    async def _process_tool_calls(
        self,
        *,
        tool_calls,
        state: _RunState,
        tool_registry,
        background_runner,
        conversation_store,
        conversation_id,
        workspace_root,
        trace_context,
    ) -> tuple[LoopResult | None, bool]:
        saw_todo = False
        for index, tool_call in enumerate(tool_calls):
            if state.tool_calls >= self.max_tool_calls:
                message = f"exceed max tool call {self.max_tool_calls}"
                conversation_store.append_record(
                    MessageRecord.developer(
                        conversation_id=conversation_id,
                        content=message,
                    )
                )
                return (
                    self._result(LoopStatus.MAX_TOOL_CALLS, state, message),
                    saw_todo,
                )

            tool_name = tool_call.function.name
            saw_todo = saw_todo or tool_name == "todo"
            tool = tool_registry.get(tool_name)
            if tool is None:
                conversation_store.append_record(
                    MessageRecord.tool(
                        conversation_id=conversation_id,
                        content=f"Unknown tool: {tool_name}",
                        tool_call_id=tool_call.id,
                    )
                )
                state.tool_calls += 1
                continue

            permission_outcome = await self._permission_decision(tool_call)
            permission = permission_outcome.decision
            if permission is PermissionDecision.DENY:
                self._trace_permission_decision(
                    trace_context,
                    tool_call,
                    decision="deny",
                    source=permission_outcome.source,
                    reason=permission_outcome.reason,
                )
                self._append_denied_tool_call(
                    conversation_store,
                    conversation_id,
                    tool_call,
                )
                continue

            if permission is PermissionDecision.ASK and not state.allow_all_actions:
                self._trace_goal_stage(
                    trace_context,
                    "permission_requested",
                    details={
                        **self._tool_trace_details(tool_call),
                        "source": permission_outcome.source,
                        "reason": permission_outcome.reason,
                    },
                )
                answer = self._request_permission(tool_call)
                if answer in {"all", "a"}:
                    state.allow_all_actions = True
                    decision = "allow_all"
                elif answer in {"no", "n"}:
                    self._trace_permission_decision(
                        trace_context,
                        tool_call,
                        decision="deny",
                        source="user",
                    )
                    self._append_denied_tool_call(
                        conversation_store,
                        conversation_id,
                        tool_call,
                    )
                    continue
                elif answer not in {"yes", "y"}:
                    self._trace_permission_decision(
                        trace_context,
                        tool_call,
                        decision="deny",
                        source="user_invalid_response",
                    )
                    self._append_denied_tool_call(
                        conversation_store,
                        conversation_id,
                        tool_call,
                        reason="answer was not yes, no, or all",
                    )
                    continue
                else:
                    decision = "allow"
                self._trace_permission_decision(
                    trace_context,
                    tool_call,
                    decision=decision,
                    source="user",
                )
            elif permission is PermissionDecision.ALLOW:
                self._trace_permission_decision(
                    trace_context,
                    tool_call,
                    decision="allow",
                    source=permission_outcome.source,
                    reason=permission_outcome.reason,
                )
            elif permission is PermissionDecision.ASK and state.allow_all_actions:
                self._trace_permission_decision(
                    trace_context,
                    tool_call,
                    decision="allow",
                    source="user_allow_all",
                )

            if background_runner.should_run_tool_call(tool_call):
                background_id = background_runner.start(tool_call)
                conversation_store.append_record(
                    MessageRecord.tool(
                        conversation_id=conversation_id,
                        content=f"Started background task {background_id}",
                        tool_call_id=tool_call.id,
                    )
                )
                state.tool_calls += 1
                self._trace_goal_stage(
                    trace_context,
                    "worker_deferred",
                    background_task_id=background_id,
                    details=self._tool_trace_details(tool_call),
                )
                self._append_skipped_tool_calls(
                    tool_calls[index + 1 :],
                    conversation_store,
                    conversation_id,
                    background_id,
                )
                message = f"Background task {background_id} is still running."
                return (
                    self._result(LoopStatus.GOAL_DEFERRED, state, message),
                    saw_todo,
                )

            self._enrich_tool_call(tool_call, state, conversation_id)
            tool_result = await run_tool(
                tool,
                tool_call,
                workspace_root=workspace_root,
            )
            self._account_subagent_result(tool_name, tool_result.content, state)
            state.tool_calls += 1
            self._append_tool_result(
                conversation_store,
                conversation_id,
                tool_call,
                tool_result,
            )

            if getattr(tool, "terminal_after_run", False):
                return (
                    self._result(
                        LoopStatus.COMPLETED,
                        state,
                        tool_result.content,
                    ),
                    saw_todo,
                )

        return None, saw_todo

    def _goal_trace_context(
        self,
        *,
        conversation_id: str,
        event_id: str | None,
        run_id: str | None,
    ) -> dict[str, str | None] | None:
        goal = getattr(self.goal_controller, "active", None)
        if goal is None or goal.conversation_id != conversation_id:
            return None
        return {
            "goal_id": goal.id,
            "conversation_id": conversation_id,
            "event_id": event_id,
            "run_id": run_id,
        }

    @staticmethod
    def _trace_goal_stage(
        trace_context,
        stage: str,
        *,
        background_task_id: str | None = None,
        details=None,
    ) -> None:
        if trace_context is None:
            return
        record_goal_stage(
            stage,
            goal_id=trace_context["goal_id"],
            conversation_id=trace_context["conversation_id"],
            event_id=trace_context.get("event_id"),
            run_id=trace_context.get("run_id"),
            background_task_id=background_task_id,
            details=details,
        )

    def _trace_permission_decision(
        self,
        trace_context,
        tool_call,
        *,
        decision: str,
        source: str,
        reason: str = "",
    ) -> None:
        details = self._tool_trace_details(tool_call)
        details.update({"decision": decision, "source": source, "reason": reason})
        self._trace_goal_stage(
            trace_context,
            "permission_decided",
            details=details,
        )

    @staticmethod
    def _tool_trace_details(tool_call) -> dict:
        try:
            arguments = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"raw_arguments": tool_call.function.arguments or ""}
        return {"tool": tool_call.function.name, "arguments": arguments}

    @staticmethod
    def _notification_tag(notification: str, tag: str) -> str | None:
        match = re.search(rf"<{tag}>(.*?)</{tag}>", notification, re.DOTALL)
        return match.group(1).strip() if match else None

    @staticmethod
    def _background_exit_code(notification: str) -> int | None:
        match = re.search(r"Exit code:\s*(-?\d+)", notification)
        return int(match.group(1)) if match else None

    @staticmethod
    def _append_skipped_tool_calls(
        tool_calls,
        conversation_store,
        conversation_id,
        background_id,
    ) -> None:
        """Close unexecuted calls so the stored tool-call sequence stays valid."""
        for tool_call in tool_calls:
            conversation_store.append_record(
                MessageRecord.tool(
                    conversation_id=conversation_id,
                    content=(
                        f"Skipped because background task {background_id} started. "
                        "Retry after it completes if this tool call is still needed."
                    ),
                    tool_call_id=tool_call.id,
                )
            )

    async def _permission_decision(self, tool_call):
        if tool_call.function.name == "bash":
            arguments = json.loads(tool_call.function.arguments or "{}")
            command = str(arguments.get("command", ""))
            detailed_decision = getattr(
                self.permission_engine,
                "decide_bash_with_llm_fallback_details",
                None,
            )
            if detailed_decision is not None:
                return await detailed_decision(command)
            decision = await self.permission_engine.decide_bash_with_llm_fallback(
                command
            )
            return PermissionOutcome(decision, "permission_engine")

        rule = Rule(tool_call.function.name, tool_call.function.arguments)
        detailed_decision = getattr(
            self.permission_engine,
            "decide_with_details",
            None,
        )
        if detailed_decision is not None:
            return detailed_decision(rule)
        return PermissionOutcome(
            self.permission_engine.decide(rule),
            "permission_engine",
        )

    @staticmethod
    def _request_permission(tool_call) -> str:
        arguments_preview = (tool_call.function.arguments or "")[:60]
        prompt = (
            f"Allow this action function: {tool_call.function.name}, "
            f"arguments: {arguments_preview}? (yes/no/all):"
        )
        input_broker = get_input_broker()
        if input_broker is None:
            answer = input(f"{prompt} ")
        else:
            answer = input_broker.request_permission(prompt)
        return answer.strip().lower()

    @staticmethod
    def _append_denied_tool_call(
        conversation_store,
        conversation_id,
        tool_call,
        reason: str | None = None,
    ) -> None:
        content = (
            f"function: {tool_call.function.name}, "
            f"arguments: {tool_call.function.arguments} is denied to run"
        )
        if reason:
            content = f"{content} because {reason}"
        conversation_store.append_record(
            MessageRecord.tool(
                conversation_id=conversation_id,
                content=content,
                tool_call_id=tool_call.id,
            )
        )

    def _enrich_tool_call(
        self,
        tool_call,
        state: _RunState,
        conversation_id: str,
    ) -> None:
        tool_name = tool_call.function.name
        if tool_name == "task":
            arguments = json.loads(tool_call.function.arguments or "{}")
            arguments["max_runs"] = self._subagent_run_budget(state.runs)
            arguments["max_tool_calls"] = self._subagent_tool_call_budget(
                state.tool_calls
            )
            arguments["parent_conversation_id"] = conversation_id
            tool_call.function.arguments = json.dumps(arguments)
        elif tool_name == "spawn_teammate":
            arguments = json.loads(tool_call.function.arguments or "{}")
            arguments["parent_conversation_id"] = conversation_id
            tool_call.function.arguments = json.dumps(arguments)

    @staticmethod
    def _account_subagent_result(
        tool_name: str,
        content: str,
        state: _RunState,
    ) -> None:
        if tool_name != "task":
            return
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            payload = {}
        state.runs += int(payload.get("runs", 0))
        state.tool_calls += int(payload.get("tool_calls", 0))

    @staticmethod
    def _append_tool_result(
        conversation_store,
        conversation_id,
        tool_call,
        tool_result,
    ) -> None:
        print(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.function.name,
                "tool_argument": tool_call.function.arguments,
                "content": tool_result.content[:2000],
            }
        )
        result_message = tool_result.to_message()
        conversation_store.append_record(
            MessageRecord.tool(
                conversation_id=conversation_id,
                content=result_message["content"],
                tool_call_id=result_message["tool_call_id"],
            )
        )

    @staticmethod
    def _update_todo_reminder(
        state: _RunState,
        *,
        saw_todo: bool,
        conversation_store,
        conversation_id,
    ) -> None:
        state.rounds_since_todo = 0 if saw_todo else state.rounds_since_todo + 1
        if state.rounds_since_todo < 3:
            return
        conversation_store.append_record(
            MessageRecord.user(
                conversation_id=conversation_id,
                content=(
                    "<reminder>Update your todos only if the task is still "
                    "multi-step. Continue using the relevant tool output.</reminder>"
                ),
            )
        )
        state.rounds_since_todo = 0

    @staticmethod
    def _result(status: LoopStatus, state: _RunState, summary: str) -> LoopResult:
        return LoopResult(
            status=status,
            runs=state.runs,
            tool_calls=state.tool_calls,
            summary=summary,
        )
