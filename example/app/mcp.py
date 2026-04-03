"""Example MCP tools and resources for the demo app."""

from __future__ import annotations

import json

from plain.mcp import mcp_resource, mcp_tool


@mcp_tool
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"


@mcp_tool(name="list_users", description="List all users in the system")
def list_users_tool() -> str:
    from app.users.models import User

    users = list(User.query.values("pk", "email"))
    return json.dumps(users, default=str)


@mcp_resource("example://info", description="Basic app information")
def app_info() -> str:
    return json.dumps(
        {
            "name": "Plain Example App",
            "version": "0.0.0",
        }
    )
