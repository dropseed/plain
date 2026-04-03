"""MCP protocol handling over JSON-RPC 2.0.

Implements the Model Context Protocol (2025-03-26 spec) server-side:
- initialize / notifications/initialized handshake
- tools/list, tools/call
- resources/list, resources/read
- ping
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from plain.logs import get_framework_logger
from plain.runtime import settings

from .registry import MCPRegistry

logger = get_framework_logger("plain.mcp")

# MCP protocol version we support
PROTOCOL_VERSION = "2025-03-26"

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class MCPServer:
    """Stateless MCP server that processes JSON-RPC messages."""

    def __init__(self, registry: MCPRegistry) -> None:
        self.registry = registry
        self._handlers: dict[str, Any] = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
        }

    def handle_message(self, raw: bytes | str) -> dict[str, Any] | None:
        """Process a single JSON-RPC message and return a response.

        Returns None for notifications (no ``id`` field).
        """
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            return _error_response(None, PARSE_ERROR, f"Parse error: {e}")

        if not isinstance(message, dict):
            return _error_response(
                None, INVALID_REQUEST, "Request must be a JSON object"
            )

        msg_id = message.get("id")
        method = message.get("method")

        if not method or not isinstance(method, str):
            return _error_response(msg_id, INVALID_REQUEST, "Missing or invalid method")

        # Notifications (no id) — we accept but don't respond
        if msg_id is None:
            self._handle_notification(method, message.get("params", {}))
            return None

        params = message.get("params", {})
        if not isinstance(params, dict):
            params = {}

        handler = self._handlers.get(method)
        if handler is None:
            return _error_response(
                msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}"
            )

        try:
            result = handler(params)
            return _success_response(msg_id, result)
        except Exception as e:
            logger.exception("MCP method error", extra={"context": {"method": method}})
            return _error_response(msg_id, INTERNAL_ERROR, f"Internal error: {e}")

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        # Accept notifications silently (e.g. notifications/initialized)
        pass

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}

        if self.registry.tools:
            capabilities["tools"] = {"listChanged": False}
        if self.registry.resources:
            capabilities["resources"] = {"listChanged": False}

        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": capabilities,
            "serverInfo": {
                "name": settings.MCP_SERVER_NAME,
                "version": settings.MCP_SERVER_VERSION,
            },
        }

    def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        tools = []
        for tool in self.registry.tools.values():
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
            )
        return {"tools": tools}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        if not tool_name:
            raise ValueError("Missing tool name")

        tool = self.registry.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        arguments = params.get("arguments", {})

        try:
            result = tool.call(arguments)
        except Exception:
            error_text = traceback.format_exc()
            return {
                "content": [{"type": "text", "text": error_text}],
                "isError": True,
            }

        # Normalize result to MCP content format
        if isinstance(result, str):
            text = result
        elif isinstance(result, dict | list):
            text = json.dumps(result, default=str)
        else:
            text = str(result)

        return {
            "content": [{"type": "text", "text": text}],
        }

    def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        resources = []
        for resource in self.registry.resources.values():
            resources.append(
                {
                    "uri": resource.uri,
                    "name": resource.name,
                    "description": resource.description,
                    "mimeType": resource.mime_type,
                }
            )
        return {"resources": resources}

    def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not uri:
            raise ValueError("Missing resource URI")

        resource = self.registry.resources.get(uri)
        if not resource:
            raise ValueError(f"Unknown resource: {uri}")

        try:
            text = resource.read()
        except Exception:
            error_text = traceback.format_exc()
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": error_text,
                    }
                ],
            }

        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": text
                    if isinstance(text, str)
                    else json.dumps(text, default=str),
                }
            ],
        }


def _success_response(msg_id: Any, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": result,
    }


def _error_response(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
