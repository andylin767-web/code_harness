import asyncio
import inspect
import json
import re
import threading
from collections.abc import Callable
from typing import Any


class BackgroundTaskRunner:
    """Run slow tool blocks in daemon threads and collect notifications."""

    MAX_NOTIFICATION_OUTPUT = 400

    SLOW_COMMAND_PATTERNS = (
        r"\b(?:pip|pip3)\s+install\b",
        r"\bnpm\s+(?:install|test|run\s+build)\b",
        r"\bcargo\s+(?:build|test)\b",
        r"\bdocker\s+build\b",
        r"\bpytest\b",
        r"\bmake(?:\s|$)",
        r"\bdeploy\b",
        r"\bcompile\b",
        "make",
    )

    def __init__(
        self,
        executor: Callable[[Any], Any],
        on_complete: Callable[[str], None] | None = None,
    ):
        self._executor = executor
        self._on_complete = on_complete
        self._counter = 0
        self._tasks: dict[str, dict[str, str]] = {}
        self._results: dict[str, str] = {}
        self._lock = threading.Lock()

    def is_slow_operation(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Fallback heuristic: commands likely to take longer than normal."""
        if tool_name != "bash":
            return False
        command = str(tool_input.get("command", "")).lower()
        return any(
            re.search(pattern, command) is not None
            for pattern in self.SLOW_COMMAND_PATTERNS
        )

    def should_run_background(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        """Explicit model request takes priority; otherwise use the heuristic."""
        if tool_input.get("run_in_background"):
            return True
        return self.is_slow_operation(tool_name, tool_input)

    def should_run_tool_call(self, tool_call: Any) -> bool:
        """Return whether an OpenAI-style tool call should run in background."""
        return self.should_run_background(
            self._tool_name_from_block(tool_call),
            self._tool_input_from_block(tool_call),
        )

    def start(self, block: Any) -> str:
        """Run a block in a daemon thread and return its background task id."""
        with self._lock:
            self._counter += 1
            bg_id = f"bg_{self._counter:04d}"
            tool_input = self._tool_input_from_block(block)
            self._tasks[bg_id] = {
                "tool_use_id": str(getattr(block, "id", "")),
                "command": str(tool_input.get("command", "")),
                "status": "running",
            }

        thread = threading.Thread(target=self._worker, args=(bg_id, block), daemon=True)
        thread.start()
        return bg_id

    def collect_completed(self) -> list[str]:
        """Collect finished tasks as task_notification messages."""
        with self._lock:
            ready_ids = [
                bg_id
                for bg_id, task in self._tasks.items()
                if task["status"] in {"completed", "failed"}
            ]

        notifications = []
        for bg_id in ready_ids:
            with self._lock:
                task = self._tasks.pop(bg_id)
                output = self._results.pop(bg_id, "")
            notifications.append(self._notification(bg_id, task, output))
        return notifications

    def has_pending(self) -> bool:
        """Return whether any background task has not been collected yet."""
        with self._lock:
            return bool(self._tasks)

    def _worker(self, bg_id: str, block: Any) -> None:
        try:
            result = self._executor(block)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            output = self._result_content(result)
            status = "completed"
        except Exception as exc:
            output = f"{type(exc).__name__}: {exc}"
            status = "failed"

        with self._lock:
            self._tasks[bg_id]["status"] = status
            self._results[bg_id] = output

        if self._on_complete is not None:
            notification = self._pop_notification(bg_id)
            self._on_complete(notification)

    def _pop_notification(self, bg_id: str) -> str:
        with self._lock:
            task = self._tasks.pop(bg_id)
            output = self._results.pop(bg_id, "")
        return self._notification(bg_id, task, output)

    @classmethod
    def _notification(
        cls,
        bg_id: str,
        task: dict[str, str],
        output: str,
    ) -> str:
        summarized_output = cls._summarize_output(output)
        return (
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>{task['status']}</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summarized_output}</summary>\n"
            f"</task_notification>"
        )

    @classmethod
    def _summarize_output(cls, output: str) -> str:
        """Preserve the beginning and end of long background output."""
        if len(output) <= cls.MAX_NOTIFICATION_OUTPUT:
            return output

        head_length = cls.MAX_NOTIFICATION_OUTPUT // 2
        tail_length = cls.MAX_NOTIFICATION_OUTPUT - head_length
        return (
            f"{output[:head_length]}\n"
            "... truncated background output ...\n"
            f"{output[-tail_length:]}"
        )

    @staticmethod
    def _result_content(result: Any) -> str:
        content = getattr(result, "content", result)
        return str(content)

    @staticmethod
    def _tool_name_from_block(block: Any) -> str:
        function = getattr(block, "function", None)
        return str(getattr(function, "name", ""))

    @staticmethod
    def _tool_input_from_block(block: Any) -> dict[str, Any]:
        block_input = getattr(block, "input", None)
        if isinstance(block_input, dict):
            return block_input

        function = getattr(block, "function", None)
        arguments = getattr(function, "arguments", None)
        if not arguments:
            return {}
        try:
            parsed_arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed_arguments, dict):
            return parsed_arguments
        return {}
