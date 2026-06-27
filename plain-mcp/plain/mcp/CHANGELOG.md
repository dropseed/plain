# plain-mcp changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-mcp@0.1.0) (2026-06-26)

Initial release of `plain.mcp` — build a Model Context Protocol (MCP) server inside a Plain app.

### What's changed

- `MCPView`: an MCP server endpoint that exposes `tools` and `resources` over the Streamable HTTP transport (JSON-RPC), with declarative or imperative tool/resource registration.
- Composable authentication — session auth via `AuthView`, a bearer-token check in `before_request`, or OAuth.
- Issuer-agnostic OAuth resource-server support: the `OAuthResourceServer` mixin + `TokenInfo` seam, an RFC 9728 protected-resource metadata view (`MCPProtectedResourceView`), and a `WWW-Authenticate` challenge, so an endpoint can accept bearer tokens from any issuer (pair with `plain.oauthserver`).
- Implements MCP protocol version 2025-11-25, with version negotiation in `initialize` and `MCP-Protocol-Version` header validation.

### Upgrade instructions

- No changes required (first release).
