from __future__ import annotations

import base64
import json
from http import HTTPStatus
from typing import Any

from plain.http import (
    HTTPException,
    JsonResponse,
    Response,
    ResponseBase,
)
from plain.logs import log_exception
from plain.runtime import settings
from plain.views.base import View

from .exceptions import MCPInvalidParams, MCPUnauthorized
from .resources import MCPResource
from .tools import MCPTool

PROTOCOL_VERSION = "2025-03-26"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNAUTHORIZED = -32001
FORBIDDEN = -32003
NOT_FOUND = -32004

_STATUS_TO_JSON_RPC_CODE: dict[int, int] = {
    400: INVALID_PARAMS,
    401: UNAUTHORIZED,
    403: FORBIDDEN,
    404: NOT_FOUND,
    500: INTERNAL_ERROR,
}


class MCPView(View):
    """An MCP server endpoint. Subclass to build your own.

    `MCPView` is a Plain View — mount it in your URLs directly:

        class AppMCP(MCPView):
            name = "myapp"
            tools = [Greet]

        # app/urls.py
        path("mcp/", AppMCP, name="mcp")

    MCPView itself does no authentication. Compose with `plain.auth.views.AuthView`
    for session auth (put `MCPView` first in the base list), or override
    `before_request()` to verify a token / custom credentials and raise
    `MCPUnauthorized` on failure. The raised exception is translated to a
    JSON-RPC 401 response by `handle_exception`.

    Register tools declaratively on the class:

        class AppMCP(MCPView):
            name = "myapp"
            tools = [Greet, Search]

    Or imperatively, which is how third-party packages attach to a shared
    MCPView they don't own (e.g. `plain.admin.mcp.AdminMCP`):

        AdminMCP.register_tool(PageViewStats)

    Handling JSON-RPC methods beyond the tools capability: define a method
    named `rpc_<method>` where slashes in the JSON-RPC method become
    underscores. Advertise the matching capability by overriding
    `get_capabilities()`:

        class AppMCP(MCPView):
            def rpc_prompts_list(self, params):
                return {"prompts": [...]}

            def get_capabilities(self):
                caps = super().get_capabilities()
                caps["prompts"] = {"listChanged": False}
                return caps
    """

    name: str = ""
    version: str = ""
    tools: list[type[MCPTool]] = []
    resources: list[type[MCPResource]] = []

    @classmethod
    def register_tool(cls, tool_cls: type[MCPTool]) -> type[MCPTool]:
        """Attach a tool to this MCPView subclass.

        Used by third-party packages to extend a shared MCPView subclass
        (e.g. `plain.admin.mcp.AdminMCP`) that they don't own:

            AdminMCP.register_tool(PageViewStats)
        """
        cls._append_unique("tools", tool_cls)
        return tool_cls

    @classmethod
    def register_resource(cls, resource_cls: type[MCPResource]) -> type[MCPResource]:
        """Attach a resource to this MCPView subclass. Parallels `register_tool`."""
        cls._append_unique("resources", resource_cls)
        return resource_cls

    @classmethod
    def _append_unique(cls, attr: str, item: type) -> None:
        # Give this class its own list on first mutation so registrations
        # don't bleed into the base class or sibling subclasses.
        if attr not in cls.__dict__:
            setattr(cls, attr, list(getattr(cls, attr)))
        existing = getattr(cls, attr)
        if item not in existing:
            existing.append(item)

    def get_tools(self) -> list[type[MCPTool]]:
        """Return the tools available for this request.

        Default: the class-level `tools` list, filtered through each
        tool's `allowed_for(self)` classmethod. Override to skip per-tool
        gates (e.g. superuser bypass) or to add dynamic tools. Returned
        list must not be mutated by callers.
        """
        return [t for t in self.tools if t.allowed_for(self)]

    def get_resources(self) -> list[type[MCPResource]]:
        """Return the resources available for this request.

        Default: the class-level `resources` list, filtered through each
        resource's `allowed_for(self)` classmethod. Override to skip
        per-resource gates or to add dynamic resources.
        """
        return [r for r in self.resources if r.allowed_for(self)]

    def handle_exception(self, exc: Exception) -> ResponseBase:
        """Translate framework exceptions into JSON-RPC responses.

        MCP clients expect JSON bodies and can't follow HTTP redirects, so
        we catch the standard auth/routing exceptions here and emit
        JSON-RPC error objects at appropriate status codes.
        """
        if isinstance(exc, MCPUnauthorized):
            return JsonResponse(
                _error_response(None, UNAUTHORIZED, str(exc)), status_code=401
            )

        status = exc.status_code if isinstance(exc, HTTPException) else 500
        if status >= 500:
            log_exception(self.request, exc)
            message = "Internal error"
        else:
            message = str(exc) or HTTPStatus(status).phrase
        return JsonResponse(
            _error_response(
                None, _STATUS_TO_JSON_RPC_CODE.get(status, INTERNAL_ERROR), message
            ),
            status_code=status,
        )

    def post(self) -> ResponseBase:
        response = self.handle_message(self.request.body)
        if response is None:
            return Response(status_code=204)
        return JsonResponse(response)

    def handle_message(self, raw: bytes | str) -> dict[str, Any] | None:
        """Process a single JSON-RPC message and return the reply dict.

        Returns None for notifications (no `id` field).
        """
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            return _error_response(None, PARSE_ERROR, f"Parse error: {e}")

        if not isinstance(message, dict):
            return _error_response(
                None, INVALID_REQUEST, "Request must be a JSON object"
            )

        if message.get("jsonrpc") != "2.0":
            return _error_response(
                message.get("id"),
                INVALID_REQUEST,
                "Missing or invalid 'jsonrpc' version; must be '2.0'",
            )

        msg_id = message.get("id")
        method = message.get("method")

        if not method or not isinstance(method, str):
            return _error_response(msg_id, INVALID_REQUEST, "Missing or invalid method")

        if msg_id is None:
            return None

        # MCP uses by-name params (objects) only. By-position (arrays) is
        # valid JSON-RPC 2.0 in general but not how MCP methods are spec'd.
        # Explicit null is accepted as "no params".
        params = message.get("params")
        if params is None:
            params = {}
        elif not isinstance(params, dict):
            return _error_response(msg_id, INVALID_PARAMS, "'params' must be an object")

        # Reject `_` so the `/` → `_` rewrite below can't be spoofed by
        # a client sending `tools_list` instead of `tools/list`.
        if "_" in method:
            return _error_response(
                msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}"
            )

        handler = getattr(self, f"rpc_{method.replace('/', '_')}", None)
        if handler is None:
            return _error_response(
                msg_id, METHOD_NOT_FOUND, f"Unknown method: {method}"
            )

        try:
            result = handler(params)
            return _success_response(msg_id, result)
        except MCPInvalidParams as e:
            return _error_response(msg_id, INVALID_PARAMS, str(e))
        except Exception as e:
            log_exception(self.request, e)
            return _error_response(msg_id, INTERNAL_ERROR, "Internal error")

    def get_capabilities(self) -> dict[str, Any]:
        """Return the capabilities dict advertised to clients at `initialize`.

        Override to advertise additional capabilities beyond `tools` /
        `resources`. Call `super().get_capabilities()` to keep the
        defaults.
        """
        capabilities: dict[str, Any] = {}
        if self.get_tools():
            capabilities["tools"] = {"listChanged": False}
        if self.get_resources():
            capabilities["resources"] = {
                "subscribe": False,
                "listChanged": False,
            }
        return capabilities

    def rpc_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": self.get_capabilities(),
            "serverInfo": {
                "name": self.name,
                "version": self.version or settings.VERSION,
            },
        }

    def rpc_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    def rpc_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": tool_cls.name,
                    "description": tool_cls.description,
                    "inputSchema": tool_cls.input_schema,
                }
                for tool_cls in self.get_tools()
            ]
        }

    def rpc_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        if not tool_name:
            raise MCPInvalidParams("Missing tool name")

        # Unauthorized tools are filtered out by `get_tools()`, so they
        # hit this same "unknown" path — existence isn't leaked.
        tool_cls = next((t for t in self.get_tools() if t.name == tool_name), None)
        if tool_cls is None:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        arguments = params.get("arguments", {})
        try:
            tool = tool_cls(**arguments)
        except TypeError as e:
            return {
                "content": [{"type": "text", "text": f"Invalid arguments: {e}"}],
                "isError": True,
            }
        tool.mcp = self

        try:
            result = tool.run()
        except Exception as e:
            log_exception(self.request, e)
            return {
                "content": [{"type": "text", "text": "Tool execution failed"}],
                "isError": True,
            }

        return {"content": _to_content_blocks(result)}

    def rpc_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        # Only static-URI resources go here; templated ones live under
        # resources/templates/list per the MCP spec.
        return {
            "resources": [
                {
                    "uri": resource_cls.uri,
                    "name": resource_cls.name,
                    "description": resource_cls.description,
                    "mimeType": resource_cls.mime_type,
                }
                for resource_cls in self.get_resources()
                if resource_cls.uri
            ]
        }

    def rpc_resources_templates_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "resourceTemplates": [
                {
                    "uriTemplate": resource_cls.uri_template,
                    "name": resource_cls.name,
                    "description": resource_cls.description,
                    "mimeType": resource_cls.mime_type,
                }
                for resource_cls in self.get_resources()
                if resource_cls.uri_template
            ]
        }

    def rpc_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not uri:
            raise MCPInvalidParams("Missing uri")

        # Unauthorized resources are filtered out by `get_resources()`, so
        # they hit this same "unknown" path — existence isn't leaked.
        resource_cls: type[MCPResource] | None = None
        matched_params: dict[str, Any] = {}
        for candidate in self.get_resources():
            try:
                match = candidate.matches(uri)
            except (TypeError, ValueError) as e:
                # Regex matched but coercion failed — URI looks like this
                # resource's template but the params don't parse.
                raise MCPInvalidParams(f"Invalid URI params: {e}") from e
            if match is not None:
                resource_cls = candidate
                matched_params = match
                break

        if resource_cls is None:
            raise MCPInvalidParams(f"Unknown resource: {uri}")

        try:
            resource = resource_cls(**matched_params)
        except TypeError as e:
            raise MCPInvalidParams(f"Invalid URI params: {e}") from e
        resource.mcp = self

        # Resources have no in-band error channel like tools' `isError`, so
        # read() exceptions propagate and surface as INTERNAL_ERROR.
        content = resource.read()

        entry: dict[str, Any] = {"uri": uri, "mimeType": resource.mime_type}
        if isinstance(content, bytes):
            entry["blob"] = _b64(content)
        else:
            entry["text"] = content
        return {"contents": [entry]}


_CONTENT_BLOCK_TYPES = {"text", "image", "audio", "resource", "resource_link"}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _to_content_blocks(value: Any) -> list[dict[str, Any]]:
    """Convert a tool's `run()` return value into MCP content blocks.

    Recognized shapes (in order):
    - `str` → one text block
    - a dict with `type` in the known content types → that single block
    - a list where every item is such a dict → those blocks, in order
    - any other `dict`/`list` → one text block with the value JSON-serialized
    - anything else → one text block with `str(value)`

    `bytes` values in `data` (image/audio) or `resource.blob` (embedded
    resource) are base64-encoded automatically.
    """
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, dict) and _is_content_block(value):
        return [_encode_binary(value)]
    if isinstance(value, list) and value and all(_is_content_block(v) for v in value):
        return [_encode_binary(v) for v in value]
    if isinstance(value, dict | list):
        return [{"type": "text", "text": json.dumps(value, default=str)}]
    return [{"type": "text", "text": str(value)}]


def _is_content_block(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") in _CONTENT_BLOCK_TYPES


def _encode_binary(block: dict[str, Any]) -> dict[str, Any]:
    """Encode `bytes` fields to base64 in-place on a content block copy."""
    block_type = block.get("type")
    if block_type in ("image", "audio"):
        data = block.get("data")
        if isinstance(data, bytes):
            return {**block, "data": _b64(data)}
    elif block_type == "resource":
        resource = block.get("resource")
        if isinstance(resource, dict):
            blob = resource.get("blob")
            if isinstance(blob, bytes):
                return {
                    **block,
                    "resource": {**resource, "blob": _b64(blob)},
                }
    return block


def _success_response(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error_response(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": code, "message": message},
    }
