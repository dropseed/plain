# plain.mcp

**Expose your Plain app to AI clients as an MCP server over HTTP.**

- [Overview](#overview)
- [Tools](#tools)
- [Resources](#resources)
- [Authentication](#authentication)
    - [Bearer token](#bearer-token)
    - [OAuth](#oauth)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can turn any Plain app into an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server by defining tools and resources with decorators. The package handles the JSON-RPC protocol, authentication, and endpoint routing.

```python
# app/mcp.py (auto-discovered)
import json

from plain.mcp import mcp_tool, mcp_resource


@mcp_tool
def create_user(email: str, name: str) -> str:
    """Create a new user account."""
    from app.users.models import User

    user = User(email=email, name=name)
    user.save()
    return f"Created user {user.id}"


@mcp_resource("myapp://users", description="List all users")
def list_users() -> str:
    from app.users.models import User

    users = list(User.query.values("id", "email"))
    return json.dumps(users, default=str)
```

Add the router to your URL config:

```python
from plain.mcp import MCPRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("mcp/", MCPRouter),
    ]
```

AI clients connect to `https://yourapp.com/mcp/` using the [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http).

## Tools

Use [`@mcp_tool`](./registry.py#mcp_tool) to register a function as an MCP tool. The function name, docstring, and type hints are used to generate the tool schema automatically.

```python
from plain.mcp import mcp_tool


@mcp_tool
def search_orders(query: str, limit: int = 10) -> str:
    """Search orders by customer name or order ID."""
    results = Order.query.filter(name__contains=query)[:limit]
    return "\n".join(str(o) for o in results)
```

You can override the name or description:

```python
@mcp_tool(name="find_orders", description="Look up orders")
def search_orders(query: str) -> str:
    ...
```

Tools can be defined in any file, but `app/mcp.py` is auto-discovered on startup.

## Resources

Use [`@mcp_resource`](./registry.py#mcp_resource) to expose read-only data with a URI:

```python
from plain.mcp import mcp_resource


@mcp_resource("myapp://config", mime_type="application/json")
def app_config() -> str:
    """Current application configuration."""
    return json.dumps({"version": "1.0", "features": ["search", "export"]})
```

Clients request resources by URI. The `mime_type` defaults to `text/plain`.

## Authentication

### Bearer token

Set a shared secret for simple token-based auth:

```bash
export PLAIN_MCP_AUTH_TOKEN="your-secret-token"
```

Clients include it in the `Authorization` header:

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

When `MCP_AUTH_TOKEN` is empty (the default), all requests are allowed — useful for local development.

### OAuth

When [`plain.oauth_provider`](../../plain-oauth-provider/plain/oauth_provider/README.md) is installed, the MCP endpoint automatically validates OAuth access tokens. Add both sets of well-known endpoints for full MCP OAuth discovery:

```python
from plain.mcp import MCPRouter, MCPWellKnownRouter
from plain.oauth_provider.urls import OAuthProviderRouter, OAuthWellKnownRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("mcp/", MCPRouter),
        include("oauth/", OAuthProviderRouter),
        include(".well-known/", OAuthWellKnownRouter),
        include(".well-known/", MCPWellKnownRouter),
    ]
```

MCP clients will automatically:

1. Discover `/.well-known/oauth-protected-resource` to find the authorization server
2. Fetch `/.well-known/oauth-authorization-server` to get endpoint URLs
3. Run the OAuth flow to get an access token
4. Use the token for MCP requests

## Settings

| Setting              | Default       | Description                             |
| -------------------- | ------------- | --------------------------------------- |
| `MCP_AUTH_TOKEN`     | `""`          | Bearer token for auth. Empty = no auth. |
| `MCP_SERVER_NAME`    | `"plain-mcp"` | Server name in MCP handshake.           |
| `MCP_SERVER_VERSION` | `"0.1.0"`     | Server version in MCP handshake.        |

All settings can be set via `PLAIN_`-prefixed environment variables (e.g., `PLAIN_MCP_AUTH_TOKEN`).

## FAQs

#### What MCP protocol version is supported?

The `2025-03-26` version of the MCP specification, using the Streamable HTTP transport. The older SSE transport is not supported.

#### How does auto-discovery work?

On startup, the package looks for `mcp.py` modules in your installed packages (similar to how `plain.jobs` discovers job classes). Any `@mcp_tool` or `@mcp_resource` decorators in those modules register automatically.

#### Do I need to handle CSRF?

No. Non-browser clients (like AI assistants) don't send `Origin` or `Sec-Fetch-Site` headers, so Plain's CSRF protection skips them automatically.

#### Can I use both bearer token and OAuth?

If `MCP_AUTH_TOKEN` is set, it takes priority. OAuth validation is only used when no static token is configured and `plain.oauth_provider` is installed.

## Installation

Install the `plain.mcp` package from [PyPI](https://pypi.org/project/plain.mcp/):

```bash
uv add plain-mcp
```

Add to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.mcp",
]
```
