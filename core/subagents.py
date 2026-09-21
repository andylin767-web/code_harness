import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from code_harness.core.agent import Agent
from code_harness.core.config import get_model_id
from code_harness.core.loop import Loop
from code_harness.core.permissions import PermissionEngine
from code_harness.core.tracing import save_trace, utc_now_iso
from code_harness.memory.context import ConversationStore, MessageRecord
from code_harness.tools.tools import get_tools

SUBAGENT_SYSTEM_PROMPT = """You are a focused subagent working for a parent agent.

Complete only the delegated task. Use the smallest useful context, do not modify
unrelated files, do not spawn more agents, and run the narrowest relevant
validation after editing. Report findings, files changed, validation, remaining
risks, and usage. Do not make final user-facing commitments.
"""


@dataclass(frozen=True)
class SubagentRequest:
    prompt: str
    parent_conversation_id: str
    max_runs: int
    max_tool_calls: int


class SubagentRunner:
    """Run a bounded, one-shot subagent with explicit runtime dependencies."""

    def __init__(self, services=None):
        self.services = services

    async def run(self, request: SubagentRequest) -> str:
        started_at = utc_now_iso()
        run_id = started_at.replace(":", "-").replace("+", "Z")
        conversation_id = f"conv_{uuid4().hex}"
        store = ConversationStore()
        workspace_root = self._workspace_root()
        registry = get_tools("sub_agent", services=self.services)
        permission_engine = PermissionEngine(workspace_root=workspace_root)
        settings_path = self._settings_path()
        if settings_path is None:
            permission_engine.load_settings_json()
        else:
            permission_engine.load_settings_json(settings_path)
        agent = Agent(
            name="Subagent",
            role="focused coding subagent",
            assignment=request.prompt,
            toolset=registry,
            system_prompt=SUBAGENT_SYSTEM_PROMPT,
            model=get_model_id(),
            workspace_root=workspace_root,
            services=self.services,
        )
        loop_options = {
            "max_runs": request.max_runs,
            "max_tool_calls": request.max_tool_calls,
        }
        if self.services is not None:
            loop_options["input_broker"] = self.services.input_broker
        loop = Loop(agent, permission_engine, **loop_options)
        store.append_record(
            MessageRecord.system(
                conversation_id=conversation_id,
                content=loop.system_prompt,
            )
        )

        try:
            result = await loop.run(store, conversation_id, request.prompt)
            return json.dumps(
                {
                    "status": result.status,
                    "runs": result.runs,
                    "tool_calls": result.tool_calls,
                    "summary": result.summary,
                    "sub_conversation_id": conversation_id,
                }
            )
        finally:
            save_trace(
                run_id=run_id,
                started_at=started_at,
                ended_at=utc_now_iso(),
                user_input=request.prompt,
                conversation_id=conversation_id,
                parent_conversation_id=request.parent_conversation_id,
                messages=store.get_records_by_conversation_id(conversation_id),
                trace_type="subagent",
                trace_dir=self._trace_dir(),
            )

    def _workspace_root(self) -> Path:
        if self.services is not None and self.services.lead_agent is not None:
            return self.services.lead_agent.workspace_root
        return Path.cwd().resolve()

    def _settings_path(self) -> Path | None:
        if self.services is None:
            return None
        return getattr(self.services, "settings_path", None)

    def _trace_dir(self) -> Path | None:
        if self.services is None:
            return None
        return self.services.state_root / "traces"
