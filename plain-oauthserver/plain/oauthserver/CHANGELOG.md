# plain-oauthserver changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-oauthserver@0.1.0) (2026-06-26)

Initial release of `plain.oauthserver` — a public-client OAuth 2.1 authorization server for Plain apps, enough to let an MCP client like Claude's custom connector connect as one of your users.

### What's changed

- Authorization-code grant with mandatory PKCE (S256), refresh-token rotation, and token revocation (RFC 7009).
- Dynamic client registration (RFC 7591) for public clients, authorization-server metadata (RFC 8414), and RFC 8707 audience binding.
- Tokens are stored as SHA-256 hashes; the `ClearExpiredOAuthTokens` chore prunes spent authorization codes and dead tokens.
- A resource-server validator, `validate_access_token`, that composes with `plain.mcp`'s `OAuthResourceServer`.

### Upgrade instructions

- No changes required (first release).
