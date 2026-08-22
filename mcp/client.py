import inspect
from dataclasses import dataclass, field
from typing import Any, Callable


class MCPError(RuntimeError):
    """Base error raised by the MCP integration boundary."""


class MCPConnectionError(MCPError):
    """Raised when an MCP client cannot service a request."""


class MCPToolError(MCPError):
    """Raised when an MCP server reports a tool execution failure."""


@dataclass(frozen=True)
class MCPToolDefinition:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    annotations: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MCPToolDefinition":
        return cls(
            name=str(value["name"]),
            description=str(value.get("description", "")),
            input_schema=dict(
                value.get("inputSchema")
                or value.get("input_schema")
                or {"type": "object", "properties": {}}
            ),
            annotations=dict(value.get("annotations") or {}),
        )


class MCPClient:
    """Async MCP client boundary backed by local handlers for development."""

    def __init__(self, name: str):
        self.name = name
        self._tools: list[MCPToolDefinition] = []
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._closed = False

    def register(
        self,
        tool_defs: list[dict[str, Any] | MCPToolDefinition],
        handlers: dict[str, Callable[..., Any]],
    ) -> None:
        """Configure the local mock transport.

        Handlers remain an implementation detail of this client; callers only
        discover definitions and invoke tools through the async MCP boundary.
        """
        self._tools = [
            definition
            if isinstance(definition, MCPToolDefinition)
            else MCPToolDefinition.from_dict(definition)
            for definition in tool_defs
        ]
        self._handlers = dict(handlers)

    async def list_tools(self) -> list[MCPToolDefinition]:
        self._ensure_open()
        return list(self._tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self._ensure_open()
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise MCPToolError(f"Unknown MCP tool '{tool_name}'")

        try:
            result = handler(**arguments)
            if inspect.isawaitable(result):
                return await result
            return result
        except MCPError:
            raise
        except Exception as exc:
            raise MCPToolError(str(exc)) from exc

    async def close(self) -> None:
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise MCPConnectionError(f"MCP server '{self.name}' is closed")
