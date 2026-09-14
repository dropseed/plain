# plain.oauthserver

**An OAuth 2.1 authorization server for Plain apps — enough to let an MCP client like Claude connect as one of your users.**

- [Overview](#overview)
- [Connecting an MCP client](#connecting-an-mcp-client)
- [Clients are public](#clients-are-public)
- [Dynamic client registration](#dynamic-client-registration)
- [Client ID Metadata Documents](#client-id-metadata-documents)
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
    urls = (
        include("oauth/", OAuthServerRouter),
        include(".well-known/", OAuthWellKnownRouter),
    )
```

After `uv run plain postgres sync` you have authorization-code + PKCE, refresh-token rotation, revocation, client registration (hosted metadata documents or dynamic registration), and discovery metadata. The authorization flow reuses your existing [`plain.auth`](../../plain-auth/plain/auth/README.md) login — the user signs in and approves on a consent screen.

The driving use case is an **end-user-facing MCP server**: a customer adds your app as a custom connector in Claude, signs in, and the connector acts on their behalf. That flow needs OAuth — there is no bearer-token-paste path in the connector UI.

## Connecting an MCP client

MCP clients self-configure over OAuth: the client hits your protected endpoint with no token, discovers this server, identifies itself (by [hosted metadata document](#client-id-metadata-documents) or by [registering](#dynamic-client-registration)), and completes a browser login + consent — you mount the routers and the client drives the rest. The endpoint-side wiring (the resource server and the discovery challenge) lives in [`plain.mcp`](../../plain-mcp/plain/mcp/README.md#oauth-for-mcp-clients), which walks the full handshake.

## Clients are public

Every client is a **public client** — it has no `client_secret`. That's the norm for MCP connectors and CLIs, which run on the user's machine and can't keep a secret. Clients are proven by PKCE on the code exchange (and by the refresh token on refresh), not a secret — so the token endpoint only advertises `token_endpoint_auth_method: "none"`.

You rarely create clients by hand — Claude presents a [hosted metadata document](#client-id-metadata-documents) and other clients [register themselves](#dynamic-client-registration) — but you can:

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

MCP has deprecated dynamic registration in favor of [Client ID Metadata Documents](#client-id-metadata-documents); it stays on by default here because clients that don't support metadata documents yet still fall back to it.

## Client ID Metadata Documents

Instead of registering, a client can present a URL as its `client_id` — an HTTPS address where it hosts a small JSON document describing itself (`client_name`, `redirect_uris`). That's a [Client ID Metadata Document](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/) (CIMD, MCP SEP-991), and it's what **Claude's custom connector uses by default**: Claude's document lives at `https://claude.ai/oauth/mcp-oauth-client-metadata`, so there's nothing registered per user and no `/oauth/register` traffic.

Nothing to set up. The metadata document advertises `client_id_metadata_document_supported`, and when an authorize request arrives with a URL `client_id`, [`cimd.py`](./cimd.py) fetches the document, checks that the document's own `client_id` is exactly that URL, and stores it as an [`OAuthApplication`](./models.py#OAuthApplication) whose `client_id` is the URL — one row per client product, shared by everyone who uses that client. The requested `redirect_uri` is checked against the document's list like any other registration, and the consent screen shows the host the document came from, since the `client_name` inside it is self-asserted.

The fetch is the risky part — the server is fetching a URL a stranger chose — so it's deliberately narrow: HTTPS only, hostnames only (no IP literals, no `localhost`), the host must resolve to public addresses, the connection is pinned to the address that was checked (a DNS answer can't change underneath it), redirects are never followed, the body is capped at 5 KB, and the whole fetch has a 5-second deadline. The token and revocation endpoints never fetch; only `/oauth/authorize` does.

Documents are cached on the row for their `Cache-Control` lifetime, clamped to between 5 minutes and 24 hours (1 hour when there's no directive). If a refetch fails, the stored copy keeps working for 7 days, so an outage at the client's host doesn't lock your users out.

Two settings control it:

- `OAUTH_SERVER_ALLOW_CLIENT_ID_METADATA_DOCUMENTS = False` turns it off — URL `client_id`s become unknown clients and the flag disappears from the metadata document.
- `OAUTH_SERVER_CLIENT_ID_METADATA_ALLOWED_HOSTS = ["claude.ai"]` restricts fetching to specific hosts. The default (`None`) fetches from any public host.

Only public clients are accepted (`token_endpoint_auth_method` absent or `"none"`, proven by PKCE); a document that asks for `private_key_jwt` or carries a client secret is rejected.

## Protecting a resource

The server issues tokens; validating them is the resource server's job. [`validate_access_token`](./resource_server.py#validate_access_token) resolves a bearer value to its live [`AccessToken`](./models.py#AccessToken) (returning `None` for unknown, expired, or revoked tokens, and enforcing audience binding when a `resource` is given):

```python
from plain.oauthserver import validate_access_token

token = validate_access_token(bearer, resource="https://myapp.com/mcp")
if token is not None:
    user = token.user
```

That's the seam for any resource server. Protecting a [`plain.mcp`](../../plain-mcp/plain/mcp/README.md) endpoint? Its `OAuthResourceServer` mixin wraps this validator and handles the `401` challenge and resource-metadata document for you — see [OAuth for MCP clients](../../plain-mcp/plain/mcp/README.md#oauth-for-mcp-clients).

## Endpoints

| Endpoint                                  | Method | Description                                                         |
| ----------------------------------------- | ------ | ------------------------------------------------------------------- |
| `/.well-known/oauth-authorization-server` | GET    | Authorization server metadata (RFC 8414)                            |
| `/oauth/authorize`                        | GET    | Consent screen (login required); a URL `client_id` is resolved here |
| `/oauth/authorize`                        | POST   | Record the approve/deny decision                                    |
| `/oauth/token`                            | POST   | Code exchange and refresh (rotation)                                |
| `/oauth/register`                         | POST   | Dynamic client registration (RFC 7591)                              |
| `/oauth/revoke`                           | POST   | Revoke a token (RFC 7009)                                           |

## Consent template

Override `oauthserver/authorize.html` in your app's templates to restyle the approval screen. It receives `application`, `scope`, and a `params` dict of the original request fields (`client_id`, `redirect_uri`, `scope`, `state`, `resource`, `code_challenge`, `code_challenge_method`) to re-submit as hidden inputs. It also gets `client_host` (the host a [metadata document](#client-id-metadata-documents) came from, or `None`), `redirect_host` (where the user will be sent back to), and `loopback_only` (`True` when every redirect URI points at the user's own machine — worth a warning, since nothing proves which local program is asking).

## Models

- [**OAuthApplication**](./models.py#OAuthApplication) — a registered public client (no secret). For a [metadata-document client](#client-id-metadata-documents) the `client_id` is the document URL and `metadata_fetched_at` / `metadata_expires_at` track the cached copy.
- [**AuthorizationCode**](./models.py#AuthorizationCode) — single-use code carrying the PKCE challenge and bound `resource`.
- [**AccessToken**](./models.py#AccessToken) — bearer token, **stored as a SHA-256 hash** so a database leak can't be replayed. Carries the granted `scope` and bound `resource`.
- [**RefreshToken**](./models.py#RefreshToken) — hashed, expiring, and rotated on every use. Scope and resource come from its linked `AccessToken`.

## Settings

| Setting                                           | Default              | Description                                             |
| ------------------------------------------------- | -------------------- | ------------------------------------------------------- |
| `OAUTH_SERVER_CODE_EXPIRY`                        | `600`                | Authorization code lifetime (seconds)                   |
| `OAUTH_SERVER_ACCESS_TOKEN_EXPIRY`                | `3600`               | Access token lifetime (seconds)                         |
| `OAUTH_SERVER_REFRESH_TOKEN_EXPIRY`               | `2592000`            | Refresh token lifetime (seconds, 30 days)               |
| `OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION`         | `True`               | Enable RFC 7591 registration                            |
| `OAUTH_SERVER_ALLOW_CLIENT_ID_METADATA_DOCUMENTS` | `True`               | Accept URL `client_id`s (CIMD)                          |
| `OAUTH_SERVER_CLIENT_ID_METADATA_ALLOWED_HOSTS`   | `None`               | Hosts to fetch metadata from (`None` = any public host) |
| `OAUTH_SERVER_SCOPES_SUPPORTED`                   | `["offline_access"]` | Scopes advertised in metadata                           |

All settings can be set via `PLAIN_`-prefixed environment variables.

## FAQs

#### Why is PKCE mandatory?

OAuth 2.1 requires PKCE for every authorization-code grant to prevent code-interception attacks. Only the `S256` method is accepted; `plain` is rejected.

#### How are tokens stored?

Access and refresh tokens are generated, returned to the client once, and persisted only as a SHA-256 hash. Validation re-hashes the incoming bearer and looks it up — the plaintext is never on disk. Authorization codes are stored directly since they're single-use and short-lived.

#### How does refresh rotation work?

Using a refresh token issues a new access + refresh pair and revokes the old pair. Refresh tokens also expire. This is required for public clients and limits exposure if a token leaks.

#### Why does every Claude user share one client?

With a [metadata document](#client-id-metadata-documents), the `client_id` is Claude's URL, so every person connecting from Claude presents the same `client_id` and shares one `OAuthApplication` row. That's by design — it's what removes the per-user registrations DCR accumulates. It also means "revoke this client" has to be scoped to a user: revoke by `(user, application)`, never by application alone, or you'd log every Claude user out at once.

#### What if the client's metadata host is down?

The stored document keeps serving for 7 days after a failed refetch, so a short outage at `claude.ai` doesn't stop anyone from connecting. A client the server has never seen before can't be resolved during the outage — the consent screen explains why instead of redirecting.

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
    ...,
]
```

Then sync the database:

```bash
uv run plain postgres sync
```
