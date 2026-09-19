import os

from pydantic import BaseModel

from code_harness.tools.tools import BaseTool


class EditFileInput(BaseModel):
    path: str
    old_text: str
    new_text: str


class EditFile(BaseTool):
    name = "edit_file"
    description = "edit the file to replace old_text with new_text"
    input_model = EditFileInput
    project_path_fields = {"path"}

    def run(self, arguments: EditFileInput):
        path = os.path.expanduser(arguments.path)

        # Read the file
        with open(path) as file:
            content = file.read()

        if arguments.old_text not in content:
            return f"Error: Text not found in {path}"

            # Replace the text
        updated_content = content.replace(arguments.old_text, arguments.new_text)

        # Write back to the same file
        with open(path, "w") as file:
            file.write(updated_content)

        return f"finish edit file: {path}"
