import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from code_harness.mcp.client import MCPClient
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
    data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    configured = data.get("mcp", {}).get("servers", [])
    if not isinstance(configured, list) or not all(
        isinstance(name, str) for name in configured
    ):
        raise ValueError("mcp.servers must be a list of server names")
    return configured


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
