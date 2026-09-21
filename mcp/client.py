import asyncio
import inspect
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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


class StdioMCPClient(MCPClient):
    """MCP JSON-RPC client for servers launched over standard I/O."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        protocol_version: str = "2025-11-25",
    ) -> None:
        super().__init__(name)
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.protocol_version = protocol_version
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._request_id = 0
        self._write_lock = asyncio.Lock()
        self._initialized = False

    async def list_tools(self) -> list[MCPToolDefinition]:
        await self._initialize()
        definitions: list[MCPToolDefinition] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = await self._request("tools/list", params)
            definitions.extend(
                MCPToolDefinition.from_dict(item) for item in result.get("tools", [])
            )
            cursor = result.get("nextCursor")
            if not cursor:
                return definitions

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        await self._initialize()
        return await self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
        self._fail_pending(MCPConnectionError(f"MCP server '{self.name}' closed"))

    async def _initialize(self) -> None:
        self._ensure_open()
        if self._initialized:
            return
        await self._start()
        await self._request(
            "initialize",
            {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "code-harness", "version": "0.1.0"},
            },
        )
        await self._notify("notifications/initialized", {})
        self._initialized = True

    async def _start(self) -> None:
        if self._process is not None:
            return
        process_env = os.environ.copy()
        process_env.update(self.env)
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )
        except OSError as exc:
            raise MCPConnectionError(
                f"Could not start MCP server '{self.name}': {exc}"
            ) from exc
        self._reader_task = asyncio.create_task(self._read_messages())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        self._ensure_open()
        self._request_id += 1
        request_id = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise MCPConnectionError(f"MCP server '{self.name}' is not running")
        payload = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        async with self._write_lock:
            process.stdin.write(payload)
            await process.stdin.drain()

    async def _read_messages(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        try:
            while line := await process.stdout.readline():
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                request_id = message.get("id")
                if request_id is None or "method" in message:
                    continue
                future = self._pending.get(request_id)
                if future is None or future.done():
                    continue
                error = message.get("error")
                if error is not None:
                    future.set_exception(
                        MCPToolError(
                            str(error.get("message", error))
                            if isinstance(error, dict)
                            else str(error)
                        )
                    )
                else:
                    future.set_result(message.get("result", {}))
            if not self._closed:
                self._fail_pending(
                    MCPConnectionError(f"MCP server '{self.name}' disconnected")
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(MCPConnectionError(str(exc)))

    async def _drain_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        try:
            while await process.stderr.readline():
                pass
        except asyncio.CancelledError:
            raise

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
