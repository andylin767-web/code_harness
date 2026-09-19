import json
from uuid import uuid4

from pydantic import BaseModel

from code_harness.tools.tools import BaseTool, get_tools


class TaskInput(BaseModel):
    prompt: str
    parent_conversation_id: str
    max_runs: int
    max_tool_calls: int


class SubAgentTaskTool(BaseTool):
    name = "task"
    description = "Spawn a subagent with fresh context."
    input_model = TaskInput
    agent_types = {"parent"}
    project_path_fields = {"path"}

    async def run(self, arguments: TaskInput):
        from code_harness.core.agent import Agent
        from code_harness.core.config import get_model_id
        from code_harness.core.loop import Loop
        from code_harness.core.permissions import PermissionEngine
        from code_harness.core.tracing import save_trace, utc_now_iso
        from code_harness.memory.context import ConversationStore, MessageRecord

        print(f"calling sub agent with {arguments}")
        SYSTEM_PROMPT = """
            You are a focused sub-agent working on behalf of a parent agent.

            Your job:
            - Complete only the delegated task.
            - Use only the provided context and permitted tools.
            - Do not make final user-facing commitments.
            - Return a concise result to the parent agent.

            Efficient programming workflow:
            - First identify the smallest useful context for the task.
            - Prefer broad, cheap discovery before reading files: list files, search names, and search symbols or config keys.
            - Read only the files that are likely to affect the task.
            - Do not repeatedly inspect similar files after you have enough evidence to proceed.
            - Form a working hypothesis early, then act on it.
            - If a direct path, symbol, traceback, or file name is provided, start there.
            - After editing, run the narrowest relevant validation available.
            - If validation cannot be run, explain why and state the residual risk.

            Boundaries:
            - Do not modify unrelated files.
            - Do not spawn additional agents.
            - Stop when the task is complete or budget is exhausted.

            Reporting:
            - Include findings, files changed, tests run, remaining risks, and usage.

            when summarizing a lot of files, process all files from each folder to minimize agent run loop
        `;"""

        started_at = utc_now_iso()
        run_id = started_at.replace(":", "-").replace("+", "Z")
        sub_conversation_id = f"conv_{uuid4().hex}"
        conversation_store = ConversationStore()
        tool_registry = get_tools("sub_agent")
        permission_engine = PermissionEngine()
        permission_engine.load_settings_json()
        agent = Agent(
            name="Sub agent",
            role="focused coding subagent",
            assignment="Complete only the delegated task with fresh context and report the result to the parent agent.",
            toolset=tool_registry,
            system_prompt=SYSTEM_PROMPT,
            model=get_model_id(),
        )
        loop = Loop(
            agent,
            permission_engine,
            max_runs=arguments.max_runs,
            max_tool_calls=arguments.max_tool_calls,
        )
        conversation_store.append_record(
            MessageRecord.system(
                conversation_id=sub_conversation_id, content=loop.system_prompt
            )
        )
        result = None
        try:
            result = await loop.run(
                conversation_store,
                sub_conversation_id,
                arguments.prompt,
            )
            return json.dumps(
                {
                    "status": result.status,
                    "runs": result.runs,
                    "tool_calls": result.tool_calls,
                    "summary": result.summary,
                    "sub_conversation_id": sub_conversation_id,
                }
            )
        finally:
            ended_at = utc_now_iso()
            save_trace(
                run_id=run_id,
                started_at=started_at,
                ended_at=ended_at,
                user_input=arguments.prompt,
                conversation_id=sub_conversation_id,
                parent_conversation_id=arguments.parent_conversation_id,
                messages=conversation_store.get_records_by_conversation_id(
                    sub_conversation_id
                ),
                trace_type="subagent",
            )
