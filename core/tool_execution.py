from typing import Any

from code_harness.core.permissions import PermissionDecision
from code_harness.memory.context import MessageRecord
from code_harness.tools.tools import run_tool


class ToolCallProcessor:
    """Apply permissions and execute one assistant turn's tool calls."""

    def __init__(self, loop: Any) -> None:
        self.loop = loop

    async def process(
        self,
        *,
        tool_calls,
        state,
        tool_registry,
        background_runner,
        conversation_store,
        conversation_id,
        workspace_root,
        trace_context,
    ):
        saw_todo = False
        for index, tool_call in enumerate(tool_calls):
            limit_result = self._enforce_limit(
                state,
                conversation_store,
                conversation_id,
                saw_todo,
            )
            if limit_result is not None:
                return limit_result

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

            if not await self._is_allowed(tool_call, state, trace_context):
                self.loop._append_denied_tool_call(
                    conversation_store,
                    conversation_id,
                    tool_call,
                )
                continue

            if background_runner.should_run_tool_call(tool_call):
                return self._start_background(
                    tool_calls,
                    index,
                    tool_call,
                    state,
                    background_runner,
                    conversation_store,
                    conversation_id,
                    trace_context,
                    saw_todo,
                )

            self.loop._enrich_tool_call(tool_call, state, conversation_id)
            tool_result = await run_tool(
                tool,
                tool_call,
                workspace_root=workspace_root,
            )
            self.loop._account_subagent_result(tool_name, tool_result.content, state)
            state.tool_calls += 1
            self.loop._append_tool_result(
                conversation_store,
                conversation_id,
                tool_call,
                tool_result,
            )
            if getattr(tool, "terminal_after_run", False):
                from code_harness.core.loop import LoopStatus

                return (
                    self.loop._result(
                        LoopStatus.COMPLETED,
                        state,
                        tool_result.content,
                    ),
                    saw_todo,
                )

        return None, saw_todo

    def _enforce_limit(
        self,
        state,
        conversation_store,
        conversation_id,
        saw_todo: bool,
    ):
        if state.tool_calls < self.loop.max_tool_calls:
            return None
        message = f"exceed max tool call {self.loop.max_tool_calls}"
        conversation_store.append_record(
            MessageRecord.developer(
                conversation_id=conversation_id,
                content=message,
            )
        )
        from code_harness.core.loop import LoopStatus

        return self.loop._result(LoopStatus.MAX_TOOL_CALLS, state, message), saw_todo

    async def _is_allowed(self, tool_call, state, trace_context) -> bool:
        outcome = await self.loop._permission_decision(tool_call)
        permission = outcome.decision
        if permission is PermissionDecision.DENY:
            self.loop._trace_permission_decision(
                trace_context,
                tool_call,
                decision="deny",
                source=outcome.source,
                reason=outcome.reason,
            )
            return False

        if permission is PermissionDecision.ALLOW:
            self.loop._trace_permission_decision(
                trace_context,
                tool_call,
                decision="allow",
                source=outcome.source,
                reason=outcome.reason,
            )
            return True

        if state.allow_all_actions:
            self.loop._trace_permission_decision(
                trace_context,
                tool_call,
                decision="allow",
                source="user_allow_all",
            )
            return True

        self.loop._trace_goal_stage(
            trace_context,
            "permission_requested",
            details={
                **self.loop._tool_trace_details(tool_call),
                "source": outcome.source,
                "reason": outcome.reason,
            },
        )
        answer = self.loop._request_permission(tool_call)
        if answer in {"all", "a"}:
            state.allow_all_actions = True
            decision = "allow_all"
        elif answer in {"yes", "y"}:
            decision = "allow"
        else:
            source = "user" if answer in {"no", "n"} else "user_invalid_response"
            self.loop._trace_permission_decision(
                trace_context,
                tool_call,
                decision="deny",
                source=source,
            )
            return False
        self.loop._trace_permission_decision(
            trace_context,
            tool_call,
            decision=decision,
            source="user",
        )
        return True

    def _start_background(
        self,
        tool_calls,
        index,
        tool_call,
        state,
        background_runner,
        conversation_store,
        conversation_id,
        trace_context,
        saw_todo,
    ):
        background_id = background_runner.start(tool_call)
        conversation_store.append_record(
            MessageRecord.tool(
                conversation_id=conversation_id,
                content=f"Started background task {background_id}",
                tool_call_id=tool_call.id,
            )
        )
        state.tool_calls += 1
        self.loop._trace_goal_stage(
            trace_context,
            "worker_deferred",
            background_task_id=background_id,
            details=self.loop._tool_trace_details(tool_call),
        )
        self.loop._append_skipped_tool_calls(
            tool_calls[index + 1 :],
            conversation_store,
            conversation_id,
            background_id,
        )
        message = f"Background task {background_id} is still running."
        from code_harness.core.loop import LoopStatus

        return self.loop._result(LoopStatus.GOAL_DEFERRED, state, message), saw_todo
