import os

from pydantic import BaseModel

from code_harness.tools.tools import BaseTool


class ReadFileInput(BaseModel):
    path: str


class ReadFile(BaseTool):
    name='read_file'
    description='read file content from the file path'
    input_model = ReadFileInput
    project_path_fields = {"path"}


    def run(self, arguments : ReadFileInput )->str:
        with open(os.path.expanduser(arguments.path), "r") as f:
                return f.read()
