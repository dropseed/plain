# plain-oauth-provider

OAuth 2.1 authorization server for Plain apps.

Implements the authorization code flow with PKCE, token issuance, refresh, and revocation — designed to work with MCP clients and any other OAuth 2.1 consumer.

## Installation

```bash
uv add plain-oauth-provider
```

Add to `INSTALLED_PACKAGES`:

```python
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.postgres",
    "plain.oauth_provider",
    # ...
]
```

## Quick start

### 1. Add URL routes

```python
from plain.oauth_provider import OAuthProviderRouter, OAuthWellKnownRouter
from plain.urls import Router, include

class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthProviderRouter),
        include(".well-known/", OAuthWellKnownRouter),
        # ...
    ]
```

### 2. Run migrations

```bash
uv run plain postgres sync
```

### 3. Register an OAuth application

```python
from plain.oauth_provider.models import OAuthApplication

app = OAuthApplication(
    name="My AI Client",
    redirect_uris="http://localhost:3000/callback",
)
app.save()
print(f"Client ID: {app.client_id}")
print(f"Client Secret: {app.client_secret}")
```

### 4. Exempt OAuth paths from CSRF

Non-browser clients (like MCP clients) bypass CSRF automatically since they don't send `Origin` or `Sec-Fetch-Site` headers. If your OAuth token endpoint is called from a browser context, add it to `CSRF_EXEMPT_PATHS`:

```python
CSRF_EXEMPT_PATHS = [r"^/oauth/token", r"^/oauth/revoke"]
```

## Endpoints

| Endpoint                                  | Method | Description                              |
| ----------------------------------------- | ------ | ---------------------------------------- |
| `/.well-known/oauth-authorization-server` | GET    | Authorization server metadata (RFC 8414) |
| `/oauth/authorize/`                       | GET    | Show consent form (requires login)       |
| `/oauth/authorize/`                       | POST   | Process user's approve/deny decision     |
| `/oauth/token/`                           | POST   | Exchange code for tokens, or refresh     |
| `/oauth/revoke/`                          | POST   | Revoke an access or refresh token        |

## Authorization flow

1. Client redirects user to `/oauth/authorize/` with `response_type=code`, `client_id`, `redirect_uri`, `code_challenge`, `code_challenge_method=S256`, and optional `state`/`scope`
2. User logs in (if needed) and sees the consent form
3. User approves → server redirects to `redirect_uri` with `code` and `state`
4. Client exchanges `code` + `code_verifier` + `client_id` + `client_secret` at `/oauth/token/`
5. Server returns `access_token`, `refresh_token`, `expires_in`
6. Client uses `Authorization: Bearer <access_token>` for API requests

PKCE (Proof Key for Code Exchange) is **mandatory** — the `plain` challenge method is not supported, only `S256`.

## Settings

| Setting                                     | Default | Description                                 |
| ------------------------------------------- | ------- | ------------------------------------------- |
| `OAUTH_PROVIDER_CODE_EXPIRY`                | `600`   | Authorization code lifetime (seconds)       |
| `OAUTH_PROVIDER_ACCESS_TOKEN_EXPIRY`        | `3600`  | Access token lifetime (seconds)             |
| `OAUTH_PROVIDER_ALLOW_DYNAMIC_REGISTRATION` | `False` | Enable RFC 7591 dynamic client registration |

## Using with plain-mcp

When both `plain-mcp` and `plain-oauth-provider` are installed, the MCP endpoint automatically validates OAuth access tokens. Add the well-known endpoints for full MCP OAuth discovery:

```python
from plain.mcp import MCPRouter, MCPWellKnownRouter
from plain.oauth_provider import OAuthProviderRouter, OAuthWellKnownRouter

class AppRouter(Router):
    namespace = ""
    urls = [
        include("mcp/", MCPRouter),
        include("oauth/", OAuthProviderRouter),
        include(".well-known/", OAuthWellKnownRouter),
        include(".well-known/", MCPWellKnownRouter),
    ]
```

MCP clients will:

1. Discover `/.well-known/oauth-protected-resource` → find the authorization server
2. Fetch `/.well-known/oauth-authorization-server` → get endpoint URLs
3. Run the OAuth flow → get an access token
4. Use the token for MCP requests

## Models

- **OAuthApplication** — registered client apps (client_id, client_secret, redirect_uris)
- **AuthorizationCode** — short-lived codes for the auth code flow
- **AccessToken** — bearer tokens with expiration
- **RefreshToken** — for token rotation (old tokens are revoked on refresh)
