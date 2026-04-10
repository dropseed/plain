"""Tools and resources for the MCP conformance suite.

The conformance tool expects specific tool/resource names with specific
behaviors — registering them here is what lets the suite actually exercise
the plain-mcp implementation.
"""

from __future__ import annotations

from plain.mcp import mcp_resource, mcp_tool


@mcp_tool(name="test_simple_text")
def test_simple_text() -> str:
    """Return a fixed text response."""
    return "This is a simple text response for testing."


@mcp_tool(name="test_error_handling")
def test_error_handling() -> str:
    """Always raise — exercises the isError response path."""
    raise RuntimeError("This tool intentionally returns an error for testing")


@mcp_resource(
    "test://static-text",
    description="Static text resource for conformance",
    mime_type="text/plain",
)
def static_text() -> str:
    return "This is the content of the static text resource."
