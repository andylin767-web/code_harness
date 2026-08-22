import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from code_harness.mcp.client import MCPClient, MCPToolDefinition, MCPToolError
from code_harness.mcp.naming import normalize_mcp_name
from code_harness.tools.tools import BaseTool


class MCPArguments(BaseModel):
    model_config = ConfigDict(extra="allow")


class MCPTool(BaseTool):
    """Expose one remotely discovered MCP capability as a harness tool."""

    auto_register = False
    agent_types = {"parent"}
    input_model = MCPArguments

    def __init__(
        self,
        server_name: str,
        client: MCPClient,
        definition: MCPToolDefinition,
    ) -> None:
        self.server_name = server_name
        self.client = client
        self.definition = definition
        self.remote_name = definition.name
        self.name = (
            f"mcp__{normalize_mcp_name(server_name)}__"
            f"{normalize_mcp_name(definition.name)}"
        )
        self.description = definition.description

    def to_litellm_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.definition.input_schema,
            },
        }

    def validate_arguments(self, raw_arguments: Any) -> MCPArguments:
        _validate_json_schema(raw_arguments, self.definition.input_schema)
        return MCPArguments.model_validate(raw_arguments)

    async def run(self, arguments: MCPArguments) -> str:
        result = await self.client.call_tool(
            self.remote_name,
            arguments.model_dump(),
        )
        return _normalize_mcp_result(result)


def _normalize_mcp_result(result: Any) -> str:
    if isinstance(result, dict) and (
        "content" in result or "isError" in result or "is_error" in result
    ):
        is_error = bool(result.get("isError", result.get("is_error", False)))
        content = result.get("content", "")
        normalized = _normalize_content(content)
        if is_error:
            raise MCPToolError(normalized or "MCP tool execution failed")
        return normalized

    content = getattr(result, "content", result)
    is_error = bool(
        getattr(result, "isError", getattr(result, "is_error", False))
    )
    normalized = _normalize_content(content)
    if is_error:
        raise MCPToolError(normalized or "MCP tool execution failed")
    return normalized


def _normalize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif hasattr(block, "text"):
                parts.append(str(block.text))
            else:
                parts.append(json.dumps(block, sort_keys=True, default=str))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    if isinstance(content, (dict, tuple)):
        return json.dumps(content, sort_keys=True, default=str)
    return str(content)


def _validate_json_schema(value: Any, schema: Any, path: str = "arguments") -> None:
    """Validate common MCP input-schema constraints without a new dependency."""
    if schema is True or not schema:
        return
    if schema is False:
        raise ValueError(f"{path} is not allowed")
    if not isinstance(schema, dict):
        raise ValueError(f"Invalid JSON schema at {path}")

    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']!r}")

    if "allOf" in schema:
        for candidate in schema["allOf"]:
            _validate_json_schema(value, candidate, path)
    if "anyOf" in schema and not _matches_any(value, schema["anyOf"], path):
        raise ValueError(f"{path} does not match any allowed schema")
    if "oneOf" in schema:
        matches = sum(
            _schema_matches(value, candidate, path)
            for candidate in schema["oneOf"]
        )
        if matches != 1:
            raise ValueError(f"{path} must match exactly one allowed schema")

    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_is_json_type(value, item) for item in expected):
            raise ValueError(f"{path} must have type {expected}")
    elif expected and not _is_json_type(value, expected):
        raise ValueError(f"{path} must have type {expected}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")

        properties = schema.get("properties", {})
        for name, child in value.items():
            if name in properties:
                _validate_json_schema(child, properties[name], f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{path}.{name} is not an allowed field")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate_json_schema(
                    child,
                    schema["additionalProperties"],
                    f"{path}.{name}",
                )

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            _validate_json_schema(child, schema["items"], f"{path}[{index}]")


def _is_json_type(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: (
            isinstance(item, (int, float)) and not isinstance(item, bool)
        ),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    check = checks.get(expected)
    return True if check is None else check(value)


def _schema_matches(value: Any, schema: Any, path: str) -> bool:
    try:
        _validate_json_schema(value, schema, path)
    except ValueError:
        return False
    return True


def _matches_any(value: Any, schemas: list[Any], path: str) -> bool:
    return any(_schema_matches(value, schema, path) for schema in schemas)
