# plain-mcp

MCP (Model Context Protocol) server for Plain apps.

Expose your app's functionality to AI clients over HTTP with authentication.

## Installation

```bash
uv add plain-mcp
```

Add `"plain.mcp"` to `INSTALLED_PACKAGES` in your settings.

## Quick start

### 1. Define tools and resources

Create `app/mcp.py` (auto-discovered):

```python
from plain.mcp import mcp_tool, mcp_resource

@mcp_tool
def create_user(email: str, name: str) -> str:
    """Create a new user account."""
    user = User(email=email, name=name)
    user.save()
    return f"Created user {user.pk}"

@mcp_resource("myapp://users", description="List all users")
def list_users() -> str:
    users = list(User.query.values("pk", "email"))
    return json.dumps(users, default=str)
```

### 2. Add the URL route

```python
from plain.mcp import MCPRouter
from plain.urls import Router, include

class AppRouter(Router):
    namespace = ""
    urls = [
        include("mcp/", MCPRouter),
        # ... other routes
    ]
```

### 3. Configure authentication

Set a bearer token for production:

```bash
export PLAIN_MCP_AUTH_TOKEN="your-secret-token"
```

Or in `app/settings.py`:

```python
MCP_AUTH_TOKEN = "your-secret-token"
```

When no token is set, all requests are allowed (development mode).

### 4. Connect your AI client

```json
{
  "mcpServers": {
    "my-app": {
      "url": "https://myapp.com/mcp/",
      "headers": {
        "Authorization": "Bearer your-secret-token"
      }
    }
  }
}
```

## Settings

| Setting              | Env var                    | Default       | Description                             |
| -------------------- | -------------------------- | ------------- | --------------------------------------- |
| `MCP_AUTH_TOKEN`     | `PLAIN_MCP_AUTH_TOKEN`     | `""`          | Bearer token for auth. Empty = no auth. |
| `MCP_SERVER_NAME`    | `PLAIN_MCP_SERVER_NAME`    | `"plain-mcp"` | Server name in MCP handshake.           |
| `MCP_SERVER_VERSION` | `PLAIN_MCP_SERVER_VERSION` | `"0.1.0"`     | Server version in MCP handshake.        |

## How it works

The package implements the [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http):

- **POST /mcp/** — JSON-RPC requests (initialize, tools/list, tools/call, resources/list, resources/read)
- **GET /mcp/** — SSE stream for server-initiated notifications
- **DELETE /mcp/** — Session termination

Authentication uses Bearer tokens in the `Authorization` header. Non-browser clients (like AI assistants) bypass CSRF automatically.

## Decorators

### `@mcp_tool`

Register a function as an MCP tool. The function's name, docstring, and type hints are used to generate the tool schema.

```python
@mcp_tool
def my_tool(arg1: str, arg2: int = 0) -> str:
    """Tool description shown to AI clients."""
    ...

@mcp_tool(name="custom_name", description="Override description")
def my_func():
    ...
```

### `@mcp_resource`

Register a function as an MCP resource with a URI.

```python
@mcp_resource("myapp://data", mime_type="application/json")
def my_data() -> str:
    """Resource description."""
    return json.dumps({"key": "value"})
```
