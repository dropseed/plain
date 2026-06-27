# plain.oauthserver

**An OAuth 2.1 authorization server for Plain apps — enough to let an MCP client like Claude connect as one of your users.**

- [Overview](#overview)
- [Connecting an MCP client](#connecting-an-mcp-client)
- [Clients are public](#clients-are-public)
- [Dynamic client registration](#dynamic-client-registration)
- [Protecting a resource](#protecting-a-resource)
- [Endpoints](#endpoints)
- [Consent template](#consent-template)
- [Models](#models)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can turn any Plain app into an OAuth 2.1 authorization server. Mount two routers — the server endpoints (anywhere) and the metadata document (at the domain root, where clients look for it):

```python
# app/urls.py
from plain.oauthserver.urls import OAuthServerRouter, OAuthWellKnownRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthServerRouter),
        include(".well-known/", OAuthWellKnownRouter),
    ]
```

After `uv run plain postgres sync` you have authorization-code + PKCE, refresh-token rotation, revocation, dynamic client registration, and discovery metadata. The authorization flow reuses your existing [`plain.auth`](../../plain-auth/plain/auth/README.md) login — the user signs in and approves on a consent screen.

The driving use case is an **end-user-facing MCP server**: a customer adds your app as a custom connector in Claude, signs in, and the connector acts on their behalf. That flow needs OAuth — there is no bearer-token-paste path in the connector UI.

## Connecting an MCP client

MCP clients self-configure over OAuth. The full handshake is automatic once both halves are in place:

1. The client hits your protected MCP endpoint with no token and gets a `401` whose `WWW-Authenticate` header points at the resource's metadata (see [Protecting a resource](#protecting-a-resource)).
2. The client reads that metadata, finds this authorization server, and fetches `/.well-known/oauth-authorization-server`.
3. It **registers itself** as a public client via [dynamic client registration](#dynamic-client-registration) — no manual setup.
4. It opens a browser to `/oauth/authorize`; the user logs in and approves.
5. It exchanges the code (with PKCE) at `/oauth/token` for an access + refresh token, then calls the MCP endpoint with `Authorization: Bearer <token>`.

You don't write any of that — you mount the routers, protect the resource, and the client drives the rest.

## Clients are public

Every client is a **public client** — it has no `client_secret`. That's the norm for MCP connectors and CLIs, which run on the user's machine and can't keep a secret. Clients are proven by PKCE on the code exchange (and by the refresh token on refresh), not a secret — so the token endpoint only advertises `token_endpoint_auth_method: "none"`.

You rarely create clients by hand — registration is dynamic — but you can:

```python
from plain.oauthserver.models import OAuthApplication

app = OAuthApplication(
    name="My CLI",
    redirect_uris="http://127.0.0.1/callback",  # space-separate multiple URIs
)
app.create()
print(app.client_id)
```

Redirect URIs must be HTTPS or loopback. Loopback URIs (`http://127.0.0.1/...`, `http://localhost/...`) match **regardless of port**, since a CLI's port isn't knowable at registration time (RFC 8252).

## Dynamic client registration

[`RegisterView`](./views.py#RegisterView) implements RFC 7591 at `/oauth/register`. A client POSTs its `redirect_uris` (and optional `client_name`) and gets back a `client_id` — always a public one. This is what lets a user paste only a URL into Claude — the client registers itself.

Registration is open, which is safe: a freshly registered client can do nothing until a real user completes the login + consent flow. Disable it with `OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION = False` if you'd rather register clients yourself.

## Protecting a resource

The server issues tokens; validating them is the resource server's job. [`validate_access_token`](./resource_server.py#validate_access_token) resolves a bearer value to its live [`AccessToken`](./models.py#AccessToken) (returning `None` for unknown, expired, or revoked tokens, and enforcing audience binding when a `resource` is given):

```python
from plain.oauthserver import validate_access_token

token = validate_access_token(bearer, resource="https://myapp.com/mcp")
if token is not None:
    user = token.user
```

For a `plain.mcp` endpoint, compose [`OAuthResourceServer`](../../plain-mcp/plain/mcp/oauth.py#OAuthResourceServer) and wire it to this validator:

```python
# app/mcp.py
from plain.mcp import MCPView, OAuthResourceServer, TokenInfo
from plain.oauthserver import validate_access_token


class AppMCP(OAuthResourceServer, MCPView):
    name = "myapp"
    tools = [...]

    def authenticate_token(self, token):
        at = validate_access_token(token, resource=self.oauth_resource)
        return TokenInfo(at.user, at.scopes) if at else None
```

`plain.mcp` handles the `401` challenge and the resource-metadata document; see its README for the routing.

## Endpoints

| Endpoint                                  | Method | Description                              |
| ----------------------------------------- | ------ | ---------------------------------------- |
| `/.well-known/oauth-authorization-server` | GET    | Authorization server metadata (RFC 8414) |
| `/oauth/authorize`                        | GET    | Consent screen (login required)          |
| `/oauth/authorize`                        | POST   | Record the approve/deny decision         |
| `/oauth/token`                            | POST   | Code exchange and refresh (rotation)     |
| `/oauth/register`                         | POST   | Dynamic client registration (RFC 7591)   |
| `/oauth/revoke`                           | POST   | Revoke a token (RFC 7009)                |

## Consent template

Override `oauthserver/authorize.html` in your app's templates to restyle the approval screen. It receives `application`, `scope`, and a `params` dict of the original request fields (`client_id`, `redirect_uri`, `scope`, `state`, `resource`, `code_challenge`, `code_challenge_method`) to re-submit as hidden inputs.

## Models

- [**OAuthApplication**](./models.py#OAuthApplication) — a registered public client (no secret).
- [**AuthorizationCode**](./models.py#AuthorizationCode) — single-use code carrying the PKCE challenge and bound `resource`.
- [**AccessToken**](./models.py#AccessToken) — bearer token, **stored as a SHA-256 hash** so a database leak can't be replayed. Carries the granted `scope` and bound `resource`.
- [**RefreshToken**](./models.py#RefreshToken) — hashed, expiring, and rotated on every use. Scope and resource come from its linked `AccessToken`.

## Settings

| Setting                                   | Default              | Description                               |
| ----------------------------------------- | -------------------- | ----------------------------------------- |
| `OAUTH_SERVER_CODE_EXPIRY`                | `600`                | Authorization code lifetime (seconds)     |
| `OAUTH_SERVER_ACCESS_TOKEN_EXPIRY`        | `3600`               | Access token lifetime (seconds)           |
| `OAUTH_SERVER_REFRESH_TOKEN_EXPIRY`       | `2592000`            | Refresh token lifetime (seconds, 30 days) |
| `OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION` | `True`               | Enable RFC 7591 registration              |
| `OAUTH_SERVER_SCOPES_SUPPORTED`           | `["offline_access"]` | Scopes advertised in metadata             |

All settings can be set via `PLAIN_`-prefixed environment variables.

## FAQs

#### Why is PKCE mandatory?

OAuth 2.1 requires PKCE for every authorization-code grant to prevent code-interception attacks. Only the `S256` method is accepted; `plain` is rejected.

#### How are tokens stored?

Access and refresh tokens are generated, returned to the client once, and persisted only as a SHA-256 hash. Validation re-hashes the incoming bearer and looks it up — the plaintext is never on disk. Authorization codes are stored directly since they're single-use and short-lived.

#### How does refresh rotation work?

Using a refresh token issues a new access + refresh pair and revokes the old pair. Refresh tokens also expire. This is required for public clients and limits exposure if a token leaks.

#### Do I need to exempt OAuth paths from CSRF?

No. Non-browser clients don't send `Origin` / `Sec-Fetch-Site`, so Plain's CSRF protection skips them. The browser-driven consent POST is same-origin and protected normally.

#### How do expired tokens get cleaned up?

Refresh rotation issues a fresh pair on every use, so spent codes and revoked/expired tokens accumulate. The [`ClearExpiredOAuthTokens`](./chores.py#ClearExpiredOAuthTokens) chore deletes them — run it on a schedule with `plain chores run`. It keeps an expired access token alive while a still-valid refresh token points at it, so refreshing never breaks.

## Installation

Install the `plain.oauthserver` package from [PyPI](https://pypi.org/project/plain.oauthserver/):

```bash
uv add plain-oauthserver
```

Add it to `INSTALLED_PACKAGES` (it needs `plain.auth` and `plain.templates`):

```python
# app/settings.py
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.postgres",
    "plain.templates",
    "plain.oauthserver",
    ...
]
```

Then sync the database:

```bash
uv run plain postgres sync
```
