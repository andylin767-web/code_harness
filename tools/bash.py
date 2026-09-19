import asyncio

from pydantic import BaseModel

from code_harness.core.permissions import PROJECT_ROOT
from code_harness.tools.tools import BaseTool


class BashInput(BaseModel):
    command: str
    cwd: str | None = None
    run_in_background: bool = False


class BashTool(BaseTool):
    name = "bash"
    description = "Run a shell command and return stdout, stderr, and exit code."
    input_model = BashInput
    project_path_fields = {"cwd"}
    workspace_default_path_fields = {"cwd"}
    time_out = 30

    async def run(self, arguments: BashInput) -> str:
        proc = await asyncio.create_subprocess_shell(
            arguments.command,
            cwd=arguments.cwd or str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=self.time_out,
        )

        stdout_text = stdout.decode(errors="replace").strip() or "(no output)"
        stderr_text = stderr.decode(errors="replace").strip() or "(no output)"
        return (
            f"Exit code: {proc.returncode}\n"
            f"Stdout:\n{stdout_text}\n"
            f"Stderr:\n{stderr_text}"
        )
