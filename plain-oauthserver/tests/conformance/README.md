# OAuth 2.1 Conformance Testing

This directory contains configuration for running the [OpenID Foundation Conformance Suite](https://gitlab.com/openid/conformance-suite/) against the plain-oauthserver.

## Quick start

### 1. Start the conformance suite

```bash
docker compose -f tests/conformance/docker-compose.yml up -d
```

The conformance suite UI will be available at `http://localhost:9999`.

### 2. Start a Plain server with plain-oauthserver installed

Use the `example/` app at the repo root (or any Plain app with `plain.oauthserver` installed and the `OAuthServerRouter` / `OAuthWellKnownRouter` mounted):

```bash
cd example
uv run plain dev
```

This typically runs at `https://<project>.localhost:8443`.

### 3. Create a test OAuth application

This server only issues **public** clients (PKCE, no secret), so create one
without a secret:

```bash
uv run plain shell -c "
from plain.oauthserver.models import OAuthApplication
app = OAuthApplication(
    name='Conformance Suite',
    redirect_uris='https://localhost.emobix.co.uk:8443/test/a/plain-oauth/callback',
)
app.create()
print(f'client_id: {app.client_id}')
"
```

### 4. Configure the conformance test

In the conformance suite UI:

1. Create a new test plan
2. Select "OAuth Authorization Server" test
3. Configure:
    - **Server metadata URL**: `https://<project>.localhost:8443/.well-known/oauth-authorization-server`
    - **Client ID**: from step 3
    - **Client authentication**: `none` (public client; PKCE is the proof)

### 5. Run the tests

Click "Run" in the conformance suite. It will test each endpoint against the OAuth 2.1 specification.

## What's tested

The conformance suite verifies:

- Authorization server metadata is correct (RFC 8414)
- Authorization endpoint behavior (RFC 6749 §4.1)
- PKCE support and enforcement (RFC 7636)
- Token endpoint (authorization code exchange, refresh)
- Token revocation (RFC 7009)
- Error response format
- Security requirements (CSRF, state parameter, etc.)
