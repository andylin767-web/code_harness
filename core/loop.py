from dataclasses import dataclass
from enum import StrEnum
import asyncio
import json
from datetime import UTC, datetime

from code_harness.core.agent import Agent
from code_harness.core.background_task import BackgroundTaskRunner
from code_harness.core.input_runtime import get_input_broker
from code_harness.events.models import EventType, new_event
from code_harness.events.queue import EventQueue
from code_harness.tools.skill_loader import DEFAULT_SKILL_DIRS, SkillLoader
from code_harness.core.llm_client import LLMClient
from code_harness.core.permissions import PermissionDecision, PermissionEngine, Rule
from code_harness.memory.context import ContextBuilder, MessageRecord
from code_harness.tools.tools import run_tool 


@dataclass
class LoopResult:
    status: str
    runs: int
    tool_calls: int
    summary: str


class LoopStatus(StrEnum):
    COMPLETED = "completed"
    MAX_RUNS = "max_runs"
    MAX_TOOL_CALLS = "max_tool_calls"
    DENIED = "denied"
    ERROR = "error"
       
class Loop:
    def __init__(
        self,
        agent: Agent,
        permission_engine: PermissionEngine,
        max_runs: int = 20,
        max_tool_calls: int = 100,
        max_run: int | None = None,
        event_queue: EventQueue | None = None,
    ):
        if max_run is not None:
            max_runs = max_run
        self.agent = agent
        self.model = agent.model
        self.max_runs = max_runs
        self.max_tool_calls =max_tool_calls
        self.event_queue = event_queue
        
        self.permission_engine= permission_engine
        self.context_Builder= ContextBuilder()
        self.skill_loader= SkillLoader(DEFAULT_SKILL_DIRS)
        self.system_prompt = agent.build_system_prompt() + f'''
                You have access to these skills:

                {self.skill_loader.list_skills_for_prompt()}

                When the user's request matches a skill, use that skill's instructions.
                If multiple skills apply, use the smallest set needed.
                If no skill applies, answer normally.
            '''
        
        print(f"system prompt: {self.system_prompt}")

    def _subagent_run_budget(self, total_run: int) -> int:
        return max(0, self.max_runs - total_run - 1)

    def _subagent_tool_call_budget(self, total_tool_call: int) -> int:
        remaining_tool_calls = max(0, self.max_tool_calls - total_tool_call)
        return remaining_tool_calls // 2
    
    async def _execute_tool_call(self, tc, tool_registry, workspace_root):
        tool = tool_registry.get(tc.function.name)
        return await run_tool(tool, tc, workspace_root=workspace_root)

    def _append_background_notifications(self, background_runner, conversation_store, conversation_id) -> int:
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

    async def _wait_for_background_tasks(self, background_runner, conversation_store, conversation_id) -> None:
        while background_runner.has_pending():
            self._append_background_notifications(background_runner, conversation_store, conversation_id)
            if not background_runner.has_pending():
                return
            await asyncio.sleep(0.1)

    async def run(self,conversation_store, conversation_id, user_message):

        workspace_root = self.agent.workspace_root
        self.permission_engine.set_workspace_root(workspace_root)
        total_tool_call=0
        rounds_since_todo =0
        llm_client= LLMClient()
        allow_all_actions = False
        tool_registry = self.agent.toolset
        on_background_complete = None
        if self.event_queue is not None:
            def on_background_complete(notification: str) -> None:
                self.event_queue.put(
                    new_event(
                        EventType.BACKGROUND_TASK,
                        notification,
                        source="background-task",
                        created_at=datetime.now(UTC).isoformat(),
                    )
                )

        background_runner = BackgroundTaskRunner(
            executor=lambda tc: self._execute_tool_call(
                tc,
                tool_registry,
                workspace_root,
            ),
            on_complete=on_background_complete,
        )
        new_user_msg = MessageRecord.user(
            conversation_id=conversation_id,
            content=user_message,
        )
        total_run=0

        conversation_store.append_record(new_user_msg)

        while total_run < self.max_runs:
            self._append_background_notifications(background_runner, conversation_store, conversation_id)
            messages = await self.context_Builder.build(conversation_store, conversation_id)
            
            response = await llm_client.send(self.model, messages, tool_registry.schemas())
           
            msg = response.choices[0].message
            assistant_message = msg.model_dump()
            conversation_store.append_record(
                MessageRecord.assistant(
                    conversation_id=conversation_id,
                    content=assistant_message,
                )
            )
            if not msg.tool_calls:
                if self.event_queue is None and background_runner.has_pending():
                    await self._wait_for_background_tasks(background_runner, conversation_store, conversation_id)
                    continue
                return LoopResult(LoopStatus.COMPLETED, total_run, total_tool_call, msg.content or "")
            
            is_todo_start =False   
            for tc in msg.tool_calls:
                
                if total_tool_call >= self.max_tool_calls:
                    conversation_store.append_record(MessageRecord.developer(conversation_id=conversation_id, content=f"exceed max tool call {self.max_tool_calls}"))
                    return LoopResult(status=LoopStatus.MAX_TOOL_CALLS, runs=total_run, tool_calls=total_tool_call, summary=f"exceed max tool call {self.max_tool_calls}")
                
                if tc.function.name=='todo':
                    is_todo_start=True

                tool = tool_registry.get(tc.function.name)

                if tool is None:
                    conversation_store.append_record(MessageRecord.tool(conversation_id=conversation_id, content=f"Unknown tool: {tc.function.name}", tool_call_id=tc.id))
                    total_tool_call += 1
                    continue

                if tc.function.name == "bash":
                    args = json.loads(tc.function.arguments or {})
                    command = str(args.get("command", ""))
                    permission_check = await self.permission_engine.decide_bash_with_llm_fallback(command)
                else:
                    permission_check = self.permission_engine.decide(
                        Rule(tc.function.name, tc.function.arguments)
                    )

                if permission_check== PermissionDecision.DENY:
                    conversation_store.append_record(MessageRecord.tool(conversation_id=conversation_id, content=f"function: {tc.function.name}, arguments: {tc.function.arguments} is denied to run", tool_call_id=tc.id))
                    continue

                if permission_check == PermissionDecision.ASK and not allow_all_actions:
                    args_preview = (tc.function.arguments or "")[:60]
                    permission_prompt = (
                        f"Allow this action function: {tc.function.name}, "
                        f"arguments: {args_preview}? (yes/no/all):"
                    )
                    input_broker = get_input_broker()
                    if input_broker is None:
                        answer = input(f"{permission_prompt} ")
                    else:
                        answer = input_broker.request_permission(
                            permission_prompt
                        )
                    answer = answer.strip().lower()

                    if answer in ("all", "a"):
                        allow_all_actions = True
                    elif answer in ("no", "n"):
                        conversation_store.append_record(MessageRecord.tool(conversation_id=conversation_id, content=f"function: {tc.function.name}, arguments: {tc.function.arguments} is denied to run", tool_call_id=tc.id))
                        continue
                    elif answer not in ("yes", "y"):
                        conversation_store.append_record(MessageRecord.tool(conversation_id=conversation_id, content=f"function: {tc.function.name}, arguments: {tc.function.arguments} is denied to run because answer was not yes, no, or all", tool_call_id=tc.id))
                        continue
                

                if background_runner.should_run_tool_call(tc):
                    bg_id = background_runner.start(tc)
                    conversation_store.append_record(
                        MessageRecord.tool(
                                    conversation_id=conversation_id,
                                    content=f"Started background task {bg_id}",
                                    tool_call_id=tc.id,
                                )
                        )
                    total_tool_call += 1
                    continue

                if tc.function.name == "task":
                    args = json.loads(tc.function.arguments or "{}")
                    args["max_runs"] = self._subagent_run_budget(total_run)
                    args["max_tool_calls"] = self._subagent_tool_call_budget(total_tool_call)
                    args["parent_conversation_id"] = conversation_id
                    tc.function.arguments = json.dumps(args)

                if tc.function.name == "spawn_teammate":
                    args = json.loads(tc.function.arguments or "{}")
                    args["parent_conversation_id"] = conversation_id
                    tc.function.arguments = json.dumps(args)

                tool_result = await run_tool(
                    tool,
                    tc,
                    workspace_root=workspace_root,
                )
                if tc.function.name == "task":
                    try:
                        task_payload = json.loads(tool_result.content)
                    except json.JSONDecodeError:
                        task_payload = {}
 
                    total_run += int(task_payload.get("runs", 0))
                    total_tool_call += int(task_payload.get("tool_calls", 0))

                total_tool_call += 1

                print({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "tool_name": tc.function.name,
                    "tool_argument": tc.function.arguments,
                    "content": tool_result.content[:2000],
                })
                tool_result_msg = tool_result.to_message()
                conversation_store.append_record(MessageRecord.tool(conversation_id=conversation_id, content=tool_result_msg["content"],tool_call_id=tool_result_msg["tool_call_id"]))
                if getattr(tool, "terminal_after_run", False):
                    return LoopResult(LoopStatus.COMPLETED, total_run, total_tool_call, tool_result.content)

            rounds_since_todo = 0 if is_todo_start else rounds_since_todo + 1
            if rounds_since_todo >= 3:
                conversation_store.append_record(MessageRecord.user(conversation_id=conversation_id, content="<reminder>Update your todos only if the task is still multi-step. Continue using the relevant tool output.</reminder>"))
                rounds_since_todo = 0

            total_run += 1
                
        conversation_store.append_record(MessageRecord.developer(conversation_id=conversation_id, content=f"exceed max run {self.max_runs}"))
        return LoopResult(status=LoopStatus.MAX_RUNS, runs=total_run, tool_calls=total_tool_call, summary=f"exceed max run {self.max_runs}")
       
