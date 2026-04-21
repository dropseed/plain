# plain.mcp

**Expose your Plain app to AI clients as an MCP server over HTTP.**

- [Overview](#overview)
- [Tools](#tools)
- [Resources](#resources)
- [Naming](#naming)
- [Multiple MCP endpoints](#multiple-mcp-endpoints)
- [Attaching tools to a shared MCP](#attaching-tools-to-a-shared-mcp)
- [Authentication](#authentication)
    - [Session auth](#session-auth-compose-with-authview)
    - [Bearer token auth](#bearer-token-auth)
    - [Public endpoints](#public-endpoints)
- [Filtering tools per request](#filtering-tools-per-request)
- [Custom JSON-RPC methods](#custom-json-rpc-methods)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

An MCP server is a subclass of [`MCPView`](./views.py#MCPView) that declares a list of `MCPTool` subclasses. `MCPView` is a Plain View — you mount it directly in your URLs.

```python
# app/mcp.py (auto-discovered on startup)
from plain.auth.views import AuthView
from plain.mcp import MCPTool, MCPView


class Greet(MCPTool):
    """Say hello to someone."""

    def __init__(self, name: str):
        self.name = name

    def run(self) -> str:
        return f"Hello, {self.name}!"


class AppMCP(MCPView, AuthView):
    name = "myapp"
    login_required = True
    tools = [Greet]
```

Mount it:

```python
# app/urls.py
from app.mcp import AppMCP
from plain.urls import Router, path


class AppRouter(Router):
    namespace = ""
    urls = [
        path("mcp/", AppMCP, name="mcp"),
    ]
```

AI clients connect to `https://yourapp.com/mcp/` using the [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http).

`name` is required. `version` defaults to `settings.VERSION` (from your `pyproject.toml`). Auth and authorization are covered below.

## Tools

Every tool is an [`MCPTool`](./tools.py#MCPTool) subclass. Arguments from the client are accepted through `__init__` (so they're typed, and can later plug into pydantic / validation). `run()` executes the tool with no extra arguments — everything it needs is already on `self`. Metadata is derived automatically:

- **Name** defaults to the class name — override with `name = "..."`
- **Description** comes from the class docstring (used verbatim — override with `description = "..."`)
- **Input schema** is derived from `__init__`'s typed signature; override by setting `input_schema = {...}` if you need custom per-parameter descriptions or JSON Schema features

```python
class SearchOrders(MCPTool):
    """Search orders by customer name or order ID."""

    def __init__(self, query: str, limit: int = 10):
        self.query = query
        self.limit = limit

    def run(self) -> str:
        return "\n".join(str(o) for o in Order.query.filter(...))
```

**Reading the invoking context.** Before `run()` is called, the dispatcher sets `self.mcp` to the `MCPView` instance that invoked the tool. Use it to read the caller's user, the HTTP request, or any subclass-specific state:

```python
from plain.mcp import MCPTool


class ListMyNotes(MCPTool):
    """List notes owned by the caller."""

    def run(self) -> list[dict]:
        return list(
            Note.query.filter(author=self.mcp.user).values("id", "title")
        )
```

**Shared state.** Tool instances are short-lived — one per MCP request. Don't use `__init__` for heavy setup; stash lookups in modules or on the MCP class.

**Return types.** `run()` returns get converted to MCP content blocks:

- **`str`** → one text block
- **a dict shaped like a content block** (`type` is one of `text`, `image`, `audio`, `resource`, `resource_link`) → that single block
- **a list of such dicts** → those blocks, in order (mixed content)
- **any other `dict`/`list`** → one text block with the value JSON-serialized

The dict shape matches the MCP spec wire format directly — you can copy from the [MCP docs](https://modelcontextprotocol.io/specification/2025-03-26/server/tools#tool-result) and return it. `bytes` in `data` (image/audio) or `resource.blob` (embedded resource) are base64-encoded automatically, so you don't touch base64 yourself:

```python
class Screenshot(MCPTool):
    """Capture a screenshot of a page."""

    def __init__(self, url: str):
        self.url = url

    def run(self) -> list:
        png_bytes = capture(self.url)
        return [
            {"type": "text", "text": f"Screenshot of {self.url}:"},
            {"type": "image", "data": png_bytes, "mimeType": "image/png"},
        ]
```

Returning a non-content dict like `{"id": 1, "name": "Alice"}` JSON-serializes into a text block — the "here's some structured data" case still works without ceremony.

## Resources

Resources are addressable data sources your server exposes for reading. Each resource is an [`MCPResource`](./resources.py#MCPResource) subclass with a URI and a `read()` method. Declare them on the MCP with `resources = [...]` (parallel to `tools`):

```python
from pathlib import Path

from plain.mcp import MCPResource
from plain.runtime import settings


class AppVersion(MCPResource):
    """Current deployed version."""

    uri = "config://app/version"
    mime_type = "text/plain"

    def read(self) -> str:
        return settings.VERSION


class AppReadme(MCPResource):
    """Project readme."""

    uri = "config://app/readme"
    mime_type = "text/markdown"

    def read(self) -> str:
        return Path("README.md").read_text()


class AppMCP(MCPView):
    name = "myapp"
    resources = [AppVersion, AppReadme]
```

Metadata is derived automatically:

- **Name** defaults to the class name — override with `name = "..."`
- **Description** comes from the class docstring (used verbatim)

**Text vs binary.** `read()` returns `str` for text (emitted as `text`) or `bytes` for binary (emitted as base64 `blob`).

**Reading the invoking context.** As with tools, `self.mcp` is set before `read()` is called — use `self.mcp.user` or `self.mcp.request` for user-scoped resources.

**Authorization.** Override `allowed_for(mcp)` on the resource (classmethod) to filter who can see it — resources that return `False` are hidden from listings and rejected from reads. Same model and hooks as tools; see [Filtering tools per request](#filtering-tools-per-request).

**Parametrized resources (URI templates).** For one class that serves many URIs — e.g. per-entity data — set `uri_template` instead of `uri` and accept the params on `__init__`:

```python
class Order(MCPResource):
    """An order by ID."""

    uri_template = "orders://{order_id}"
    mime_type = "application/json"

    def __init__(self, order_id: int):
        self.order_id = order_id

    def read(self) -> str:
        return str(Order.query.get(pk=self.order_id))
```

Templates follow [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) level 1 — `{name}` placeholders match a single path segment. Extracted params are coerced to the `__init__` annotation for `int`, `float`, `bool`; other types come through as strings. Setting both `uri` and `uri_template` is an error.

Templated resources appear under `resources/templates/list` (not `resources/list`); clients then resolve a concrete URI and call `resources/read` with it.

## Naming

`name` is the identifier your MCP server advertises to clients — it shows up in MCP client UIs alongside other registered servers, so it needs to be recognizable out of context.

- **Single MCP endpoint** — use your app's name (typically matches `settings.NAME` from `pyproject.toml`)
- **Multiple endpoints in one app** — prefix with the role: `myapp-public`, `myapp-admin`
- **A package shipping an MCP** — use the package's own name

## Multiple MCP endpoints

Create one `MCPView` subclass per endpoint. Each is mounted at its own path with its own tool surface and auth.

```python
# app/mcp.py
from plain.auth.views import AuthView
from plain.mcp import MCPUnauthorized, MCPView


class AppMCP(MCPView, AuthView):
    name = "myapp-api"
    login_required = True
    tools = [ListCustomerOrders]


class StaffMCP(MCPView, AuthView):
    name = "myapp-staff"
    login_required = True
    tools = [DescribeSchema]

    def check_auth(self):
        super().check_auth()  # login_required from AuthView
        if not self.user.is_staff:
            raise MCPUnauthorized("Staff only")
```

```python
# app/urls.py
urls = [
    path("api/mcp/", AppMCP, name="app_mcp"),
    path("staff/mcp/", StaffMCP, name="staff_mcp"),
]
```

## Attaching tools to a shared MCP

Packages that need to contribute tools to an MCP they don't own (for example, adding a page-views tool to `plain.admin.mcp.AdminMCP`) use the `register_tool()` classmethod:

```python
# plain/pageviews/mcp.py
from plain.admin.mcp import AdminMCP
from plain.mcp import MCPTool


class PageViewStats(MCPTool):
    """Page view summary for the last N days."""

    def __init__(self, days: int = 7):
        self.days = days

    def run(self) -> dict:
        ...


AdminMCP.register_tool(PageViewStats)
```

`register_tool()` accepts an `MCPTool` subclass. The attached tool inherits the host MCP's auth policy; tighter gating goes on the tool itself via `allowed_for()` (see [Authorization](#authorization)).

## Authentication

The base `MCPView` class does nothing auth-related — auth comes from whatever you compose on top of it. Override `before_request()` and raise `MCPUnauthorized` on failure; `handle_exception` translates it to a JSON-RPC 401 (MCP clients can't follow HTTP redirects, so redirect-to-login behavior isn't appropriate here).

### Session auth — compose with `AuthView`

For MCP endpoints consumed by users already signed into your Plain app, compose `MCPView` with [`plain.auth.views.AuthView`](../../plain-auth/plain/auth/README.md). Put `MCPView` first in the base list so its `handle_exception` — which emits JSON-RPC errors — takes precedence over `AuthView`'s HTML redirect rendering.

```python
from plain.auth.views import AuthView
from plain.mcp import MCPView


class AppMCP(MCPView, AuthView):
    name = "myapp"
    login_required = True
```

`login_required` / `admin_required` / `self.user` / `check_auth()` come from `AuthView`. `LoginRequired` automatically becomes a JSON-RPC 401 because it's an `HTTPException(status_code=401)` that `MCPView.handle_exception` maps through its status-code table.

For role-based gating, override `check_auth()`:

```python
class StaffMCP(MCPView, AuthView):
    name = "myapp-staff"
    login_required = True

    def check_auth(self):
        super().check_auth()
        if not self.user.is_staff:
            raise MCPUnauthorized("Staff only")
```

Importing `plain.auth` is required only for this pattern — token-only deployments can ignore it.

### Bearer token auth

For external integrations (CLI tools, remote clients, CI), subclass `MCPView` directly and check a header in `before_request()`:

```python
import hmac
import os

from plain.mcp import MCPView, MCPUnauthorized


class APIKeyMCP(MCPView):
    name = "myapp-api"

    def before_request(self) -> None:
        header = self.request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise MCPUnauthorized("Missing or invalid Authorization header")
        if not hmac.compare_digest(header[7:], os.environ["MCP_TOKEN"]):
            raise MCPUnauthorized("Invalid auth token")
```

Clients send the token in their config:

```json
{
  "mcpServers": {
    "my-app": {
      "url": "https://myapp.com/mcp/",
      "headers": {"Authorization": "Bearer <token>"}
    }
  }
}
```

### Public endpoints

The base `MCPView` class has no auth by default — subclassing `MCPView` without overriding `before_request` gives you a public endpoint. There's no "allow all" default to silently swap out; the absence of an auth check is visible in the class definition itself.

## Filtering tools per request

Two hooks, one narrow and one broad:

**1. Per-tool via `MCPTool.allowed_for(mcp)`.** A classmethod on the tool, checked before the tool is instantiated — the natural place for tool-level policies (auth, feature flags, tenant restrictions). The default `get_tools()` / `get_resources()` filter through this automatically.

```python
class AdminTool(MCPTool):
    @classmethod
    def allowed_for(cls, mcp) -> bool:
        return mcp.user is not None and mcp.user.is_admin


class DeleteUser(AdminTool):
    """Delete a user account.

    Args:
        user_id: ID of the user to delete.
    """

    def __init__(self, user_id: int):
        self.user_id = user_id

    def run(self) -> str:
        ...
```

Tools that return `False` from `allowed_for()` are hidden from `tools/list` and rejected from `tools/call` as "unknown tool" — existence isn't leaked. Same for resources and `resources/read`.

**2. Cross-cutting via `get_tools()` / `get_resources()` override.** For whole-endpoint policies — readonly mode, superuser bypass, dynamic tool sets — override the getter and return whatever list you want. Skipping `super()` bypasses `allowed_for`:

```python
class AppMCP(MCPView, AuthView):
    name = "myapp"
    login_required = True

    def get_tools(self):
        if self.user and self.user.is_superuser:
            return self.tools  # superuser sees everything, skipping allowed_for
        tools = super().get_tools()  # applies each tool's allowed_for
        if settings.READONLY_MODE:
            tools = [t for t in tools if not getattr(t, "mutates", False)]
        return tools
```

**Row-level filtering** ("only this user's notes") belongs inside `run()`/`read()` via `self.mcp.user` — not in the gating layer.

## Custom JSON-RPC methods

`plain.mcp` ships `tools/*` and `resources/*` with first-class classes. Everything else in the MCP spec — prompts, logging, completions, sampling — you implement directly on your `MCPView` subclass by defining a method named `rpc_<method>`. Slashes in the JSON-RPC method become underscores.

The pattern:

1. Write an `rpc_<method>` method that takes a `params` dict and returns the response dict (as defined by the [MCP spec](https://modelcontextprotocol.io/specification/2025-03-26/server) for that method)
2. Advertise the capability in `get_capabilities()` so clients know to call it
3. Raise `MCPInvalidParams` for bad caller input; anything else becomes a generic `INTERNAL_ERROR` with the exception logged server-side

### Example: prompts

Here's a complete prompts implementation. Note that nothing in `plain.mcp` knows about prompts — it's pure dispatch + dict responses.

```python
from plain.mcp import MCPInvalidParams, MCPView


_PROMPTS = [
    {
        "name": "summarize",
        "description": "Summarize a piece of text",
        "arguments": [
            {
                "name": "text",
                "description": "Text to summarize",
                "required": True,
            },
        ],
    },
    {
        "name": "standup",
        "description": "Draft a daily standup update",
    },
]


class AppMCP(MCPView):
    name = "myapp"

    def rpc_prompts_list(self, params):
        return {"prompts": _PROMPTS}

    def rpc_prompts_get(self, params):
        name = params.get("name")
        args = params.get("arguments") or {}

        if name == "summarize":
            text = args.get("text")
            if not text:
                raise MCPInvalidParams("Missing 'text' argument")
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": f"Summarize the following in 2 sentences:\n\n{text}",
                        },
                    }
                ]
            }

        if name == "standup":
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "Draft today's standup based on my recent commits and PRs.",
                        },
                    }
                ]
            }

        raise MCPInvalidParams(f"Unknown prompt: {name}")

    def get_capabilities(self):
        caps = super().get_capabilities()
        caps["prompts"] = {"listChanged": False}
        return caps
```

The same pattern works for any capability. `rpc_logging_setLevel`, `rpc_completion_complete`, etc. — consult the MCP spec for the method name and response shape.

### Overriding built-ins

The shipped handlers (`rpc_initialize`, `rpc_ping`, `rpc_tools_list`, `rpc_tools_call`, `rpc_resources_list`, `rpc_resources_templates_list`, `rpc_resources_read`) use the same dispatch — override them on your subclass if you need to change the defaults.

## FAQs

#### What MCP protocol version is supported?

The `2025-03-26` version of the MCP specification, using the Streamable HTTP transport. The older SSE transport is not supported.

#### Are resource subscriptions supported?

No. `resources/subscribe` and `resources/unsubscribe` require a long-lived server-to-client stream (for pushing `notifications/resources/updated`) and cross-worker fan-out of change events — neither is implemented yet. Clients that need fresh data should re-read the resource. The capabilities advertised to clients reflect this (`resources.subscribe: false`).

#### How does auto-discovery work?

On startup, `plain.mcp` imports `mcp` modules from installed packages (similar to how `plain.jobs` discovers job classes). Defining your `MCPView` subclass at module level is what makes it discoverable by packages that want to attach tools via `register_tool()`.

#### Do I need to handle CSRF?

No. Non-browser clients (like AI assistants) don't send `Origin` or `Sec-Fetch-Site` headers, so Plain's CSRF protection skips them automatically.

#### Why are arguments on `__init__` instead of `run()`?

Putting args on `__init__` makes each call a typed object (like a dataclass or pydantic model), which is the natural shape for validation hooks later and lets `run()` + any helper methods share `self.x` without re-threading parameters. `run()` stays no-arg and side-effect-shaped.

#### Why aren't tools just functions?

Classes uniformly handle state, grouped authorization (`AdminTool` base classes), and future validation/hooks. Supporting both functions and classes meant two parallel APIs; picking one keeps the mental model small.

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
