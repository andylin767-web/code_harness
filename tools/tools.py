import inspect
import json
import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Iterable, Literal

from pydantic import BaseModel, ValidationError

from code_harness.core.permissions import PROJECT_ROOT


class EmptyInput(BaseModel):
    pass


class BaseTool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]] = EmptyInput
    concurrent_safe: ClassVar[bool] = False
    project_path_fields: ClassVar[set[str]] = set()
    workspace_default_path_fields: ClassVar[set[str]] = set()
    agent_types: ClassVar[set[str]] = {"parent", "sub_agent"}
    terminal_after_run: ClassVar[bool] = False
    auto_register: ClassVar[bool] = True

    def to_litellm_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }

    async def execute(self, arguments: BaseModel) -> Any:
        result = self.run(arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    def validate_arguments(self, raw_arguments: Any) -> BaseModel:
        """Validate decoded tool arguments before workspace enforcement."""
        return self.input_model.model_validate(raw_arguments)

    def dump_arguments(self, arguments: BaseModel) -> dict[str, Any]:
        """Return validated arguments in the form passed to permissions/traces."""
        return arguments.model_dump()

    @abstractmethod
    def run(self, arguments: BaseModel) -> Any:
        """Run the tool with validated Pydantic arguments."""


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    name: str
    arguments: dict[str, Any] | None
    content: str
    error: str | None = None

    def to_message(self) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] | None = None):
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or []:
            self.register(tool)

    @classmethod
    def auto_load(
        cls,
        packages: Iterable[str] | None = None,
        agent_type: Literal["parent", "sub_agent"] | None = None,
    ) -> "ToolRegistry":
        """Import packages, then register all currently imported BaseTool subclasses."""
        registry = cls()
        for package in packages or []:
            registry.load_package(package)
        registry.register_loaded_subclasses(agent_type=agent_type)
        return registry

    @classmethod
    def for_agent(
        cls,
        agent_type: Literal["parent", "sub_agent"],
        packages: Iterable[str] | None = None,
    ) -> "ToolRegistry":
        return cls.auto_load(packages or ["code_harness.tools"], agent_type=agent_type)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def register_many(self, tools: Iterable[BaseTool]) -> None:
        """Register tools atomically after checking the entire batch."""
        pending = list(tools)
        names = [tool.name for tool in pending]
        duplicate_names = {name for name in names if names.count(name) > 1}
        collisions = set(names).intersection(self._tools)
        conflicts = sorted(duplicate_names | collisions)
        if conflicts:
            raise ValueError(
                f"Tool name collision: {', '.join(conflicts)}"
            )
        for tool in pending:
            self._tools[tool.name] = tool

    def unregister(self, name: str, tool: BaseTool | None = None) -> bool:
        """Remove a tool, optionally only when the exact instance still owns it."""
        current = self._tools.get(name)
        if current is None or (tool is not None and current is not tool):
            return False
        del self._tools[name]
        return True

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.to_litellm_schema() for tool in self._tools.values()]

    def values(self) -> list[BaseTool]:
        return list(self._tools.values())

    def register_loaded_subclasses(self, agent_type: str | None = None) -> None:
        for tool_cls in _all_tool_subclasses(BaseTool):
            if inspect.isabstract(tool_cls):
                continue
            if not tool_cls.auto_register:
                continue
            if agent_type is not None and agent_type not in tool_cls.agent_types:
                continue
            self.register(tool_cls())

    def load_package(self, package_name: str) -> None:
        package = importlib.import_module(package_name)
        if not hasattr(package, "__path__"):
            return
        for module_info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
            importlib.import_module(module_info.name)


def get_tools(agent_type: Literal["parent", "sub_agent"]) -> ToolRegistry:
    return ToolRegistry.for_agent(agent_type)


async def run_tool(
    tool: BaseTool,
    tool_call: Any,
    workspace_root: Path = PROJECT_ROOT,
) -> ToolResult:
    """Run one tool call and normalize success/failure into a tool message."""
    arguments_text = tool_call.function.arguments
    try:
        raw_arguments = json.loads(arguments_text or "{}")
    except json.JSONDecodeError as exc:
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.function.name,
            arguments=None,
            content=f"Invalid tool arguments: {arguments_text}",
            error=str(exc),
        )

    try:
        arguments = tool.validate_arguments(raw_arguments)
    except (ValidationError, TypeError, ValueError) as exc:
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool.name,
            arguments=raw_arguments if isinstance(raw_arguments, dict) else None,
            content=f"Invalid tool arguments: {exc}",
            error=str(exc),
        )

    try:
        arguments = enforce_workspace_scope(tool, arguments, workspace_root)
    except PermissionError as exc:
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool.name,
            arguments=tool.dump_arguments(arguments),
            content=f"Permission denied: {exc}",
            error=str(exc),
        )

    try:
        result = await tool.execute(arguments)
    except Exception as exc:
        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool.name,
            arguments=tool.dump_arguments(arguments),
            content=f"Tool execution failed: {exc}",
            error=str(exc),
        )

    return ToolResult(
        tool_call_id=tool_call.id,
        name=tool.name,
        arguments=tool.dump_arguments(arguments),
        content=str(result),
    )


def _all_tool_subclasses(tool_cls: type[BaseTool]) -> list[type[BaseTool]]:
    subclasses = []
    for subclass in tool_cls.__subclasses__():
        subclasses.append(subclass)
        subclasses.extend(_all_tool_subclasses(subclass))
    return subclasses


def resolve_in_workspace(path: str, workspace_root: str | Path) -> str:
    root = Path(workspace_root).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate

    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise PermissionError(f"Path outside active workspace: {resolved}")
    return str(resolved)


def resolve_in_project(path: str) -> str:
    """Compatibility wrapper for callers using the primary workspace."""
    return resolve_in_workspace(path, PROJECT_ROOT)


def enforce_workspace_scope(
    tool: BaseTool,
    arguments: BaseModel,
    workspace_root: str | Path,
) -> BaseModel:
    updates = {}
    for field_name in tool.project_path_fields:
        value = getattr(arguments, field_name, None)
        if value is None:
            if field_name in tool.workspace_default_path_fields:
                updates[field_name] = str(Path(workspace_root).resolve())
            continue
        updates[field_name] = resolve_in_workspace(str(value), workspace_root)

    if not updates:
        return arguments
    return arguments.model_copy(update=updates)


def enforce_project_scope(tool: BaseTool, arguments: BaseModel) -> BaseModel:
    """Compatibility wrapper for callers using the primary workspace."""
    return enforce_workspace_scope(tool, arguments, PROJECT_ROOT)
