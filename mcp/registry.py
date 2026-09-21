import json
import os
from collections.abc import Callable, Iterable
from pathlib import Path

from code_harness.mcp.client import MCPClient, StdioMCPClient
from code_harness.mcp.tool import MCPTool
from code_harness.tools.tools import ToolRegistry

MCPClientFactory = Callable[[], MCPClient]


class MCPRegistry:
    """Own MCP client sessions and their dynamically registered tools."""

    def __init__(
        self,
        server_factories: dict[str, MCPClientFactory] | None = None,
    ) -> None:
        self.clients: dict[str, MCPClient] = {}
        self._tools: dict[str, list[MCPTool]] = {}
        self._server_factories = (
            dict(server_factories) if server_factories is not None else MOCK_SERVERS
        )

    @classmethod
    def from_settings(cls, settings_path: str | Path) -> "MCPRegistry":
        """Build a registry from mock names or real stdio server definitions."""
        configurations = configured_mcp_server_definitions(settings_path)
        factories: dict[str, MCPClientFactory] = {}
        for name, configuration in configurations.items():
            if configuration is None:
                try:
                    factories[name] = MOCK_SERVERS[name]
                except KeyError as exc:
                    raise ValueError(f"Unknown mock MCP server '{name}'") from exc
                continue
            factories[name] = _stdio_factory(name, configuration)
        return cls(factories)

    async def connect_mcp(
        self,
        name: str,
        tool_registry: ToolRegistry,
    ) -> str:
        if name in self.clients:
            return f"MCP server '{name}' already connected"

        factory = self._server_factories.get(name)
        if factory is None:
            available = ", ".join(sorted(self._server_factories)) or "none"
            raise ValueError(f"Unknown server '{name}'. Available: {available}")

        client = factory()
        try:
            definitions = await client.list_tools()
            tools = [MCPTool(name, client, definition) for definition in definitions]
            tool_registry.register_many(tools)
        except Exception:
            await client.close()
            raise

        self.clients[name] = client
        self._tools[name] = tools
        tool_names = [tool.name for tool in tools]
        return (
            f"Connected to MCP server '{name}'. Discovered {len(tools)} tools: "
            f"{', '.join(tool_names)}"
        )

    async def connect_many(
        self,
        names: Iterable[str],
        tool_registry: ToolRegistry,
    ) -> list[str]:
        messages = []
        connected = []
        try:
            for name in names:
                was_connected = name in self.clients
                messages.append(await self.connect_mcp(name, tool_registry))
                if not was_connected:
                    connected.append(name)
        except Exception:
            for name in reversed(connected):
                await self.disconnect_mcp(name, tool_registry)
            raise
        return messages

    async def disconnect_mcp(
        self,
        name: str,
        tool_registry: ToolRegistry,
    ) -> bool:
        client = self.clients.pop(name, None)
        tools = self._tools.pop(name, [])
        if client is None:
            return False

        for tool in tools:
            tool_registry.unregister(tool.name, tool=tool)
        await client.close()
        return True

    async def close(self, tool_registry: ToolRegistry) -> None:
        for name in list(self.clients):
            await self.disconnect_mcp(name, tool_registry)


def configured_mcp_servers(settings_path: str | Path) -> list[str]:
    """Read the ordered MCP server list from harness settings."""
    return list(configured_mcp_server_definitions(settings_path))


def configured_mcp_server_definitions(
    settings_path: str | Path,
) -> dict[str, dict | None]:
    """Read legacy mock names or named stdio MCP configurations."""
    data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    configured = data.get("mcp", {}).get("servers", [])
    if isinstance(configured, list) and all(
        isinstance(name, str) for name in configured
    ):
        return dict.fromkeys(configured)
    if not isinstance(configured, dict):
        raise ValueError("mcp.servers must be a list or object")
    definitions = {}
    for name, value in configured.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ValueError("MCP server definitions must be named objects")
        if value.get("transport", "stdio") != "stdio":
            raise ValueError(f"MCP server '{name}' must use stdio transport")
        command = value.get("command")
        args = value.get("args", [])
        env = value.get("env", {})
        if not isinstance(command, str) or not command:
            raise ValueError(f"MCP server '{name}' requires a command")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError(f"MCP server '{name}' args must be strings")
        if not isinstance(env, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in env.items()
        ):
            raise ValueError(f"MCP server '{name}' env must contain strings")
        definitions[name] = value
    return definitions


def _stdio_factory(name: str, configuration: dict) -> MCPClientFactory:
    command = configuration["command"]
    args = list(configuration.get("args", []))
    env = {
        key: _expand_env_reference(value)
        for key, value in configuration.get("env", {}).items()
    }
    protocol_version = configuration.get("protocolVersion", "2025-11-25")
    return lambda: StdioMCPClient(
        name,
        command,
        args=args,
        env=env,
        protocol_version=protocol_version,
    )


def _expand_env_reference(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        variable = value[2:-1]
        try:
            return os.environ[variable]
        except KeyError as exc:
            raise ValueError(
                f"Required environment variable is not set: {variable}"
            ) from exc
    return value


def _mock_server_docs() -> MCPClient:
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            {
                "name": "search",
                "description": "Search documentation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "annotations": {"readOnlyHint": True},
            },
            {
                "name": "get_version",
                "description": "Get API version.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                "annotations": {"readOnlyHint": True},
            },
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        },
    )
    return client


def _mock_server_deploy() -> MCPClient:
    client = MCPClient("deploy")
    client.register(
        tool_defs=[
            {
                "name": "trigger",
                "description": "Trigger a deployment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
                "annotations": {"destructiveHint": True},
            },
            {
                "name": "status",
                "description": "Check deployment status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
                "annotations": {"readOnlyHint": True},
            },
        ],
        handlers={
            "trigger": lambda service: f"[deploy] Triggered: {service}",
            "status": lambda service: f"[deploy] {service}: running (v1.4.2)",
        },
    )
    return client


MOCK_SERVERS: dict[str, MCPClientFactory] = {
    "docs": _mock_server_docs,
    "deploy": _mock_server_deploy,
}
