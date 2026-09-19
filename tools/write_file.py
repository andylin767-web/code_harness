import os

from pydantic import BaseModel

from code_harness.tools.tools import BaseTool


class WriteFileInput(BaseModel):
    content: str
    path: str


class WriteFile(BaseTool):
    name = "write_file"
    description = "write the content to file using path"
    input_model = WriteFileInput
    project_path_fields = {"path"}

    def run(self, arguments: WriteFileInput) -> str:
        os.makedirs(os.path.dirname(arguments.path) or ".", exist_ok=True)
        with open(arguments.path, "w") as f:
            f.write(arguments.content)
        return f"Wrote {len(arguments.content)} bytes to {arguments.path}"
