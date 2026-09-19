import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from code_harness.core.permissions import PermissionDecision, PermissionEngine, Rule
from code_harness.mcp.client import MCPClient
from code_harness.mcp.registry import MCPRegistry
from code_harness.tools.tools import ToolRegistry, get_tools, run_tool


def tool_call(name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call-{name}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class MCPToolTests(IsolatedAsyncioTestCase):
    async def test_discovery_registers_tools_and_preserves_remote_schema(self):
        tools = ToolRegistry()
        mcp = MCPRegistry()

        message = await mcp.connect_mcp("docs", tools)

        tool = tools.get("mcp__docs__search")
        self.assertIsNotNone(tool)
        self.assertIn("Discovered 2 tools", message)
        schema = tool.to_litellm_schema()["function"]
        self.assertEqual(schema["name"], "mcp__docs__search")
        self.assertEqual(schema["parameters"]["required"], ["query"])

    async def test_tool_dispatches_to_original_remote_name(self):
        received = []
        client = MCPClient("custom")

        async def handler(query):
            received.append(query)
            return {"content": [{"type": "text", "text": f"found {query}"}]}

        client.register(
            tool_defs=[
                {
                    "name": "search.docs",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ],
            handlers={"search.docs": handler},
        )
        registry = ToolRegistry()
        mcp = MCPRegistry({"custom": lambda: client})
        await mcp.connect_mcp("custom", registry)

        result = await run_tool(
            registry.get("mcp__custom__search_docs"),
            tool_call("mcp__custom__search_docs", {"query": "agents"}),
        )

        self.assertIsNone(result.error)
        self.assertEqual(result.content, "found agents")
        self.assertEqual(received, ["agents"])

    async def test_invalid_arguments_are_rejected_before_dispatch(self):
        calls = []
        client = MCPClient("validation")
        client.register(
            tool_defs=[
                {
                    "name": "lookup",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"count": {"type": "integer"}},
                        "required": ["count"],
                        "additionalProperties": False,
                    },
                }
            ],
            handlers={"lookup": lambda count: calls.append(count)},
        )
        registry = ToolRegistry()
        await MCPRegistry({"validation": lambda: client}).connect_mcp(
            "validation", registry
        )

        missing = await run_tool(
            registry.get("mcp__validation__lookup"),
            tool_call("mcp__validation__lookup", {}),
        )
        wrong_type = await run_tool(
            registry.get("mcp__validation__lookup"),
            tool_call("mcp__validation__lookup", {"count": "three"}),
        )

        self.assertIsNotNone(missing.error)
        self.assertIn("missing required fields", missing.content)
        self.assertIsNotNone(wrong_type.error)
        self.assertIn("must have type integer", wrong_type.content)
        self.assertEqual(calls, [])

    async def test_server_error_becomes_failed_tool_result(self):
        client = MCPClient("errors")
        client.register(
            tool_defs=[{"name": "fail", "inputSchema": {"type": "object"}}],
            handlers={
                "fail": lambda: {
                    "isError": True,
                    "content": [{"type": "text", "text": "remote failure"}],
                }
            },
        )
        registry = ToolRegistry()
        await MCPRegistry({"errors": lambda: client}).connect_mcp("errors", registry)

        result = await run_tool(
            registry.get("mcp__errors__fail"),
            tool_call("mcp__errors__fail", {}),
        )

        self.assertIsNotNone(result.error)
        self.assertIn("remote failure", result.content)

    async def test_normalized_collisions_fail_without_partial_registration(self):
        client = MCPClient("collision")
        client.register(
            tool_defs=[
                {"name": "same.name", "inputSchema": {"type": "object"}},
                {"name": "same name", "inputSchema": {"type": "object"}},
            ],
            handlers={"same.name": lambda: "a", "same name": lambda: "b"},
        )
        registry = ToolRegistry()
        mcp = MCPRegistry({"collision": lambda: client})

        with self.assertRaisesRegex(ValueError, "Tool name collision"):
            await mcp.connect_mcp("collision", registry)

        self.assertEqual(registry.values(), [])
        self.assertNotIn("collision", mcp.clients)

    async def test_disconnect_removes_owned_tools_and_closes_client(self):
        registry = ToolRegistry()
        mcp = MCPRegistry()
        await mcp.connect_mcp("docs", registry)
        client = mcp.clients["docs"]

        disconnected = await mcp.disconnect_mcp("docs", registry)

        self.assertTrue(disconnected)
        self.assertIsNone(registry.get("mcp__docs__search"))
        with self.assertRaisesRegex(Exception, "closed"):
            await client.list_tools()

    async def test_mcp_tools_default_to_ask_and_are_not_auto_loaded(self):
        decision = PermissionEngine().decide(
            Rule("mcp__docs__search", json.dumps({"query": "tools"}))
        )

        self.assertEqual(decision, PermissionDecision.ASK)
        self.assertIsNone(get_tools("parent").get("mcp__docs__search"))
        self.assertIsNone(get_tools("sub_agent").get("mcp__docs__search"))
