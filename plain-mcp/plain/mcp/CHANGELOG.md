# plain-mcp changelog

## [0.3.0](https://github.com/dropseed/plain/releases/plain-mcp@0.3.0) (2026-07-10)

### What's changed

- `tools/call` arguments are now validated against the tool's advertised input schema before the tool is instantiated. A missing or wrong-typed argument comes back as a clear, model-fixable `isError` message (e.g. `Invalid arguments: 'limit' must be an integer`) instead of blowing up inside `run()` and being logged as a server exception. Validation covers the schema shapes derived from type hints — primitives, `Literal[...]` enums, `list[T]`, `T | None` — and follows JSON Schema semantics (booleans are not integers; `5.0` is a valid integer). If you hand-write an `input_schema` with richer JSON Schema keywords (`oneOf`, `$ref`, `pattern`, numeric bounds), those pass through unvalidated — check them in `__init__` or `run()` yourself. ([04e6309f7b](https://github.com/dropseed/plain/commit/04e6309f7b))
- Parameters with no annotation, `Any`, or an unrecognized type now advertise a permissive empty schema (accepts any JSON value) instead of `{"type": "string"}`, so clients are no longer steered into sending strings for values that aren't. ([04e6309f7b](https://github.com/dropseed/plain/commit/04e6309f7b))
- `*args` / `**kwargs` parameters on a tool's `__init__` are no longer advertised as schema properties — previously a `**kwargs` tool advertised a required `kwargs` property that no client could ever satisfy. ([04e6309f7b](https://github.com/dropseed/plain/commit/04e6309f7b))

### Upgrade instructions

- No changes required for tools whose type hints match what clients actually send. If a tool was knowingly accepting schema-mismatched arguments (e.g. a param annotated `int` that clients send as a string), those calls are now rejected before `__init__` — loosen the annotation (or hand-write `input_schema`) to keep accepting them.

## [0.2.1](https://github.com/dropseed/plain/releases/plain-mcp@0.2.1) (2026-06-30)

### What's changed

- Documentation only: the MCP endpoint examples now use a slashless path (`/mcp` rather than `/mcp/`) consistently across the README and the `MCPView` docstring. No code or behavior changes. ([0399d8b](https://github.com/dropseed/plain/commit/0399d8b1ad))

### Upgrade instructions

- No changes required.

## [0.2.0](https://github.com/dropseed/plain/releases/plain-mcp@0.2.0) (2026-06-28)

### What's changed

- New `MCPToolError` exception, exported from `plain.mcp`. Raise it from a tool's `run()` to signal an expected, caller-facing failure (bad input, not found, forbidden): the message is returned to the client with `isError: true` — MCP's in-result error channel, so the model can self-correct — and it is _not_ logged as a server exception. Any other exception is still treated as a bug: logged server-side and returned as an opaque "Tool execution failed" ([4989aeb](https://github.com/dropseed/plain/commit/4989aeb488)).
- New optional `annotations` attribute on `MCPTool`. Set it to a raw MCP-wire-format dict (e.g. `{"readOnlyHint": True}`) to advertise [tool annotation hints](https://modelcontextprotocol.io/specification/2025-11-25/server/tools#tool-annotations); clients like Claude group read-only tools and gate approval on the rest. The dict is emitted verbatim — any current or future spec hint works without a `plain.mcp` change — and a tool that sets no annotations carries no `annotations` object at all. Inherited like any class attribute, so a shared base tool can set it once ([88588a0](https://github.com/dropseed/plain/commit/88588a0108)).
- Documented the typed `self.mcp` pattern: re-annotate `mcp` on a per-app base tool or resource (`mcp: AppMCP`) for typed access to your view's `user`, `scopes`, and other subclass attributes. The full MCP↔OAuth client handshake walkthrough now lives in this README as well ([3460d76](https://github.com/dropseed/plain/commit/3460d76137)).

### Upgrade instructions

- No changes required. Optionally raise `MCPToolError` for expected tool failures, and set `annotations = {"readOnlyHint": True}` on read-only tools so clients can group and auto-allow them.

## [0.1.0](https://github.com/dropseed/plain/releases/plain-mcp@0.1.0) (2026-06-26)

Initial release of `plain.mcp` — build a Model Context Protocol (MCP) server inside a Plain app.

### What's changed

- `MCPView`: an MCP server endpoint that exposes `tools` and `resources` over the Streamable HTTP transport (JSON-RPC), with declarative or imperative tool/resource registration.
- Composable authentication — session auth via `AuthView`, a bearer-token check in `before_request`, or OAuth.
- Issuer-agnostic OAuth resource-server support: the `OAuthResourceServer` mixin + `TokenInfo` seam, an RFC 9728 protected-resource metadata view (`MCPProtectedResourceView`), and a `WWW-Authenticate` challenge, so an endpoint can accept bearer tokens from any issuer (pair with `plain.oauthserver`).
- Implements MCP protocol version 2025-11-25, with version negotiation in `initialize` and `MCP-Protocol-Version` header validation.

### Upgrade instructions

- No changes required (first release).
