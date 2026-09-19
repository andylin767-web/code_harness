from typing import Literal

from pydantic import BaseModel

from code_harness.tools.tools import BaseTool


class Item(BaseModel):
    id: int
    text: str
    status: Literal["pending", "in_progress", "completed"]


class TodoInput(BaseModel):
    todos: list[Item]


class TodoManager(BaseTool):
    name = "todo"
    description = "Update task list. Track progress on multi-step tasks."
    input_model = TodoInput

    def update(self, items: list[Item]) -> str:
        validated, in_progress_count = [], 0
        for item in items:
            status = item.status
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item.id, "text": item.text, "status": item.status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress")
        self.items = validated
        return self.render()

    def run(self, arguments: TodoInput):
        return self.update(arguments.todos)

    def render(self) -> str:
        if not getattr(self, "items", []):
            return "No todos."

        lines = []
        for item in self.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")

        done = sum(1 for item in self.items if item["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)
