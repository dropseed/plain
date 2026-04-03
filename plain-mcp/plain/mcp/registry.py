from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints


class Tool:
    """A registered MCP tool."""

    __slots__ = ("name", "description", "fn", "input_schema")

    def __init__(
        self,
        *,
        name: str,
        description: str,
        fn: Callable[..., Any],
        input_schema: dict[str, Any],
    ) -> None:
        self.name = name
        self.description = description
        self.fn = fn
        self.input_schema = input_schema

    def call(self, arguments: dict[str, Any]) -> Any:
        return self.fn(**arguments)


class Resource:
    """A registered MCP resource."""

    __slots__ = ("uri", "name", "description", "mime_type", "fn")

    def __init__(
        self,
        *,
        uri: str,
        name: str,
        description: str,
        mime_type: str,
        fn: Callable[..., Any],
    ) -> None:
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type
        self.fn = fn

    def read(self) -> str:
        return self.fn()


class MCPRegistry:
    """Central registry for MCP tools and resources."""

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}
        self.resources: dict[str, Resource] = {}

    def register_tool(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        tool_name = name or getattr(fn, "__name__", "unknown")
        tool_description = description or getattr(fn, "__doc__", None) or ""
        input_schema = _build_input_schema(fn)
        self.tools[tool_name] = Tool(
            name=tool_name,
            description=tool_description.strip(),
            fn=fn,
            input_schema=input_schema,
        )

    def register_resource(
        self,
        fn: Callable[..., Any],
        *,
        uri: str,
        name: str | None = None,
        description: str | None = None,
        mime_type: str = "application/json",
    ) -> None:
        resource_name = name or getattr(fn, "__name__", "unknown")
        resource_description = description or getattr(fn, "__doc__", None) or ""
        self.resources[uri] = Resource(
            uri=uri,
            name=resource_name,
            description=resource_description.strip(),
            mime_type=mime_type,
            fn=fn,
        )


# Global registry instance
mcp_registry = MCPRegistry()


def mcp_tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Register a function as an MCP tool.

    Usage:
        @mcp_tool
        def create_user(email: str, name: str) -> str:
            '''Create a new user.'''
            ...

        @mcp_tool(name="custom_name")
        def my_func():
            ...
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        mcp_registry.register_tool(f, name=name, description=description)
        return f

    if fn is not None:
        # Called as @mcp_tool without parentheses
        return decorator(fn)

    # Called as @mcp_tool(...) with arguments
    return decorator


def mcp_resource(
    uri: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str = "application/json",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function as an MCP resource.

    Usage:
        @mcp_resource("myapp://users")
        def list_users() -> str:
            '''List all users.'''
            return json.dumps([...])
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        mcp_registry.register_resource(
            fn, uri=uri, name=name, description=description, mime_type=mime_type
        )
        return fn

    return decorator


# -- Helpers ------------------------------------------------------------------

# Maps Python type annotations to JSON Schema types.
_PYTHON_TO_JSON_SCHEMA: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _build_input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Derive a JSON Schema ``object`` from *fn*'s type hints."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        prop: dict[str, Any] = {}
        hint = hints.get(param_name)
        if hint is not None:
            prop["type"] = _PYTHON_TO_JSON_SCHEMA.get(hint, "string")
        else:
            prop["type"] = "string"

        properties[param_name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema
