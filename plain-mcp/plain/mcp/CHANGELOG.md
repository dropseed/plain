# plain-mcp changelog

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
