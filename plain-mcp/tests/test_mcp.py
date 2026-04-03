from __future__ import annotations

import json
from typing import Any

from plain.mcp.protocol import MCPServer
from plain.mcp.registry import MCPRegistry


def _make_request(
    method: str, params: dict[str, Any] | None = None, msg_id: int = 1
) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
    )


class TestMCPProtocol:
    def setup_method(self) -> None:
        self.registry = MCPRegistry()
        self.server = MCPServer(self.registry)

    def test_initialize(self) -> None:
        response = self.server.handle_message(_make_request("initialize"))
        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "protocolVersion" in response["result"]
        assert "serverInfo" in response["result"]

    def test_ping(self) -> None:
        response = self.server.handle_message(_make_request("ping"))
        assert response is not None
        assert response["result"] == {}

    def test_unknown_method(self) -> None:
        response = self.server.handle_message(_make_request("bogus/method"))
        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == -32601

    def test_parse_error(self) -> None:
        response = self.server.handle_message(b"not json")
        assert response is not None
        assert "error" in response
        assert response["error"]["code"] == -32700

    def test_notification_returns_none(self) -> None:
        # Notifications have no id
        msg = json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        )
        response = self.server.handle_message(msg)
        assert response is None

    def test_tools_list_empty(self) -> None:
        response = self.server.handle_message(_make_request("tools/list"))
        assert response is not None
        assert response["result"]["tools"] == []

    def test_tools_list_with_tool(self) -> None:
        def greet(name: str) -> str:
            """Say hello."""
            return f"Hello, {name}!"

        self.registry.register_tool(greet)
        response = self.server.handle_message(_make_request("tools/list"))
        assert response is not None
        tools = response["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "greet"
        assert tools[0]["description"] == "Say hello."
        assert tools[0]["inputSchema"]["properties"]["name"]["type"] == "string"
        assert "name" in tools[0]["inputSchema"]["required"]

    def test_tools_call(self) -> None:
        def add(a: int, b: int) -> str:
            return str(int(a) + int(b))

        self.registry.register_tool(add)
        response = self.server.handle_message(
            _make_request("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}})
        )
        assert response is not None
        content = response["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "5"

    def test_tools_call_unknown(self) -> None:
        response = self.server.handle_message(
            _make_request("tools/call", {"name": "nonexistent", "arguments": {}})
        )
        assert response is not None
        assert "error" in response

    def test_tools_call_error_returns_iserror(self) -> None:
        def bad_tool() -> str:
            raise RuntimeError("something broke")

        self.registry.register_tool(bad_tool)
        response = self.server.handle_message(
            _make_request("tools/call", {"name": "bad_tool", "arguments": {}})
        )
        assert response is not None
        result = response["result"]
        assert result["isError"] is True
        assert "RuntimeError" in result["content"][0]["text"]

    def test_resources_list_empty(self) -> None:
        response = self.server.handle_message(_make_request("resources/list"))
        assert response is not None
        assert response["result"]["resources"] == []

    def test_resources_list_with_resource(self) -> None:
        def my_data() -> str:
            """Some data."""
            return '{"key": "value"}'

        self.registry.register_resource(my_data, uri="test://data")
        response = self.server.handle_message(_make_request("resources/list"))
        assert response is not None
        resources = response["result"]["resources"]
        assert len(resources) == 1
        assert resources[0]["uri"] == "test://data"
        assert resources[0]["name"] == "my_data"

    def test_resources_read(self) -> None:
        def my_data() -> str:
            return json.dumps({"key": "value"})

        self.registry.register_resource(my_data, uri="test://data")
        response = self.server.handle_message(
            _make_request("resources/read", {"uri": "test://data"})
        )
        assert response is not None
        contents = response["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "test://data"
        assert json.loads(contents[0]["text"]) == {"key": "value"}

    def test_resources_read_unknown(self) -> None:
        response = self.server.handle_message(
            _make_request("resources/read", {"uri": "test://nonexistent"})
        )
        assert response is not None
        assert "error" in response


class TestRegistry:
    def test_mcp_tool_decorator_no_args(self) -> None:
        registry = MCPRegistry()

        def my_tool(x: str) -> str:
            """Do something."""
            return x

        registry.register_tool(my_tool)
        assert "my_tool" in registry.tools
        assert registry.tools["my_tool"].description == "Do something."

    def test_mcp_tool_decorator_with_args(self) -> None:
        registry = MCPRegistry()

        def my_tool(x: str) -> str:
            return x

        registry.register_tool(my_tool, name="custom", description="Custom desc")
        assert "custom" in registry.tools
        assert registry.tools["custom"].description == "Custom desc"

    def test_input_schema_required_vs_optional(self) -> None:
        registry = MCPRegistry()

        def my_tool(required: str, optional: str = "default") -> str:
            return required

        registry.register_tool(my_tool)
        schema = registry.tools["my_tool"].input_schema
        assert "required" in schema["required"]
        assert "optional" not in schema.get("required", [])
        assert "required" in schema["properties"]
        assert "optional" in schema["properties"]
