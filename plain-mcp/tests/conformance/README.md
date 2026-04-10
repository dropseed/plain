# MCP Conformance Testing

This directory contains instructions for running the [MCP Conformance Test Framework](https://github.com/modelcontextprotocol/conformance) against a plain-mcp server.

Unlike the OAuth conformance suite, the MCP conformance framework is distributed as an npm package, so no Docker or long-running containers are required — just `npx`.

## Quick start

### 1. Start a Plain server with plain-mcp installed

Use the `example/` app at the repo root (or any Plain app with `plain.mcp` installed and `MCPRouter` mounted):

```bash
cd example
uv run plain dev
```

The server will be available at `https://<project>.localhost:8443`, with the MCP endpoint at `/mcp/`.

Make sure `app/mcp.py` registers at least one `@mcp_tool` and one `@mcp_resource` so the conformance suite has something to exercise:

```python
# app/mcp.py
from plain.mcp import mcp_tool, mcp_resource


@mcp_tool
def echo(text: str) -> str:
    """Return the input text unchanged."""
    return text


@mcp_resource("example://hello", description="A greeting")
def hello() -> str:
    return "Hello from plain-mcp"
```

### 2. Disable auth for the conformance run

The MCP conformance tool does not send bearer tokens or OAuth credentials, so leave `MCP_AUTH_TOKEN` unset and do **not** install `plain.oauth_provider` in this server. With no token configured, plain-mcp allows all requests — which is what the conformance framework expects.

### 3. Run the conformance suite

In a separate terminal:

```bash
npx @modelcontextprotocol/conformance server --url https://<project>.localhost:8443/mcp/
```

To see which scenarios are available:

```bash
npx @modelcontextprotocol/conformance list --server
```

To run a single scenario:

```bash
npx @modelcontextprotocol/conformance server \
    --url https://<project>.localhost:8443/mcp/ \
    --scenario server-initialize
```

Add `--verbose` for full request/response output. Results are written to `results/server-<scenario>-<timestamp>/checks.json`.

## What's tested

The MCP conformance framework verifies:

- `initialize` handshake and capability negotiation
- `tools/list` and `tools/call` behavior
- `resources/list` and `resources/read` behavior
- JSON-RPC 2.0 framing (request/response/notification)
- Error codes and response shapes
- Streamable HTTP transport semantics (the `2025-03-26` spec)
