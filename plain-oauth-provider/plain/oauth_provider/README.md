# plain.oauth_provider

**OAuth 2.1 authorization server for Plain apps.**

- [Overview](#overview)
- [Endpoints](#endpoints)
- [Authorization flow](#authorization-flow)
- [Registering applications](#registering-applications)
- [Consent template](#consent-template)
- [Models](#models)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can add OAuth 2.1 authorization to any Plain app. This is useful for letting third-party clients (like AI assistants, CLI tools, or other apps) access your API on behalf of your users.

```python
from plain.oauth_provider.urls import OAuthProviderRouter, OAuthWellKnownRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthProviderRouter),
        include(".well-known/", OAuthWellKnownRouter),
    ]
```

After adding the routes and running `uv run plain postgres sync`, you have a fully working OAuth 2.1 server with PKCE, token refresh, and revocation.

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
3. User approves — server redirects to `redirect_uri` with `code` and `state`
4. Client exchanges `code` + `code_verifier` + `client_id` + `client_secret` at `/oauth/token/`
5. Server returns `access_token`, `refresh_token`, and `expires_in`
6. Client uses `Authorization: Bearer <access_token>` for API requests

PKCE (Proof Key for Code Exchange) is **mandatory** — only the `S256` challenge method is supported.

## Registering applications

Create an [`OAuthApplication`](./models.py#OAuthApplication) to get a `client_id` and `client_secret`:

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

You can register multiple redirect URIs by separating them with spaces:

```python
app = OAuthApplication(
    name="My App",
    redirect_uris="http://localhost:3000/callback https://myapp.com/callback",
)
```

## Consent template

The built-in consent template at `oauth_provider/authorize.html` shows the application name and requested scopes. You can override it by placing your own template at the same path in your app's template directory.

The template receives these context variables:

- `application` — the [`OAuthApplication`](./models.py#OAuthApplication) instance
- `scope` — the requested scope string
- `redirect_uri`, `response_type`, `client_id`, `state`, `code_challenge`, `code_challenge_method` — the original authorization request parameters

## Models

- [**OAuthApplication**](./models.py#OAuthApplication) — registered client apps with `client_id`, `client_secret`, and `redirect_uris`
- [**AuthorizationCode**](./models.py#AuthorizationCode) — short-lived codes for the authorization code flow, including PKCE challenge data
- [**AccessToken**](./models.py#AccessToken) — bearer tokens with expiration and revocation
- [**RefreshToken**](./models.py#RefreshToken) — for token rotation (old tokens are revoked on refresh)

## Settings

| Setting                                     | Default | Description                                 |
| ------------------------------------------- | ------- | ------------------------------------------- |
| `OAUTH_PROVIDER_CODE_EXPIRY`                | `600`   | Authorization code lifetime (seconds)       |
| `OAUTH_PROVIDER_ACCESS_TOKEN_EXPIRY`        | `3600`  | Access token lifetime (seconds)             |
| `OAUTH_PROVIDER_ALLOW_DYNAMIC_REGISTRATION` | `False` | Enable RFC 7591 dynamic client registration |

All settings can be set via `PLAIN_`-prefixed environment variables.

## FAQs

#### Why is PKCE mandatory?

OAuth 2.1 requires PKCE for all authorization code grants. This prevents authorization code interception attacks. Only the `S256` method is supported — the `plain` method is intentionally not allowed.

#### Do I need to exempt OAuth paths from CSRF?

Non-browser clients (like MCP clients and CLI tools) don't send `Origin` or `Sec-Fetch-Site` headers, so Plain's CSRF protection skips them automatically. If your token endpoint is called from a browser context, add it to `CSRF_EXEMPT_PATHS`:

```python
CSRF_EXEMPT_PATHS = [r"^/oauth/token", r"^/oauth/revoke"]
```

#### How does token refresh work?

When a client uses a refresh token, the server issues a new access token and a new refresh token, and revokes the old refresh token. This is called **token rotation** and limits the window of exposure if a refresh token is compromised.

#### What authentication method does the token endpoint use?

`client_secret_post` — the client sends `client_id` and `client_secret` in the request body. This is the most common method for non-browser clients.

## Installation

Install the `plain.oauth-provider` package from [PyPI](https://pypi.org/project/plain.oauth-provider/):

```bash
uv add plain-oauth-provider
```

Add to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.postgres",
    "plain.oauth_provider",
    ...
]
```

Run migrations after installation:

```bash
uv run plain postgres sync
```
