from pydantic import BaseModel, Field

from code_harness.core.subagents import SubagentRequest, SubagentRunner
from code_harness.tools.tools import BaseTool


class TaskInput(BaseModel):
    prompt: str = Field(min_length=1)
    parent_conversation_id: str
    max_runs: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)


class SubAgentTaskTool(BaseTool):
    name = "task"
    description = "Run a focused, bounded subagent with fresh context."
    input_model = TaskInput
    agent_types = {"parent"}

    def __init__(self, services=None):
        self.runner = SubagentRunner(services)

    async def run(self, arguments: TaskInput) -> str:
        return await self.runner.run(SubagentRequest(**arguments.model_dump()))
