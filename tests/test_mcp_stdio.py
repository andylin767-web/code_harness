import sys
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from code_harness.mcp.client import StdioMCPClient

SERVER_SOURCE = r"""
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fixture", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [{
                "name": "echo",
                "description": "Echo text",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }]
        }
    elif method == "tools/call":
        text = message["params"]["arguments"]["text"]
        result = {"content": [{"type": "text", "text": text}]}
    else:
        result = {}
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0",
        "id": message["id"],
        "result": result,
    }) + "\n")
    sys.stdout.flush()
"""


class StdioMCPClientTests(IsolatedAsyncioTestCase):
    async def test_discovers_and_calls_tool_over_real_subprocess_stdio(self):
        with TemporaryDirectory() as directory:
            server = f"{directory}/server.py"
            with open(server, "w", encoding="utf-8") as file:
                file.write(SERVER_SOURCE)
            client = StdioMCPClient(
                "fixture",
                sys.executable,
                ["-u", server],
            )
            self.addAsyncCleanup(client.close)

            definitions = await client.list_tools()
            result = await client.call_tool("echo", {"text": "hello"})

            self.assertEqual([item.name for item in definitions], ["echo"])
            self.assertEqual(
                result,
                {"content": [{"type": "text", "text": "hello"}]},
            )
