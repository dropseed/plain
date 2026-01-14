# plain.csrf

**Cross-Site Request Forgery (CSRF) protection using modern request headers.**

- [Overview](#overview)
- [How it works](#how-it-works)
- [Exempt paths](#exempt-paths)
- [Trusted origins](#trusted-origins)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Plain provides modern CSRF protection based on [Filippo Valsorda's 2025 research](https://words.filippo.io/csrf/) using `Sec-Fetch-Site` headers and origin validation. The protection is automatic and requires no changes to your forms or templates.

The [`CsrfViewMiddleware`](./middleware.py#CsrfViewMiddleware) runs on every request and blocks cross-origin `POST`, `PUT`, `PATCH`, and `DELETE` requests. Safe methods like `GET`, `HEAD`, and `OPTIONS` are always allowed.

## How it works

The middleware uses a layered approach to validate requests:

1. **Safe methods pass through** - `GET`, `HEAD`, and `OPTIONS` requests are always allowed since they should not modify server state.

2. **Exempt paths skip validation** - Paths matching patterns in `CSRF_EXEMPT_PATHS` bypass all CSRF checks.

3. **Trusted origins are allowed** - Requests from origins in `CSRF_TRUSTED_ORIGINS` pass through.

4. **Sec-Fetch-Site header check** - Modern browsers send this header indicating the request origin:
    - `same-origin` or `none`: Allowed (request came from your site or was user-initiated)
    - `cross-site` or `same-site`: Blocked (request came from another domain or subdomain)

5. **Origin header fallback** - For older browsers without `Sec-Fetch-Site`, the middleware compares the `Origin` header against the request's `Host`.

6. **Non-browser requests pass** - Requests without either header (like curl or API clients) are allowed since they are not subject to browser CSRF attacks.

## Exempt paths

You can disable CSRF protection for specific paths using regex patterns. This is useful for API endpoints, webhooks, or health checks that receive requests from external services.

```python
# app/settings.py
CSRF_EXEMPT_PATHS = [
    r"^/api/",             # All API endpoints
    r"^/api/v\d+/",        # Versioned APIs: /api/v1/, /api/v2/, etc.
    r"/webhooks/.*",       # All webhook paths
    r"/webhooks/github/",  # Specific webhook
    r"/health$",           # Exact match for /health endpoint
]
```

Patterns use Python regex with `re.search()` against the full URL path including the leading slash.

**Pattern examples:**

| Pattern           | Matches                      | Does not match  |
| ----------------- | ---------------------------- | --------------- |
| `r"^/api/"`       | `/api/users/`, `/api/posts/` | `/v2/api/`      |
| `r"/webhooks/.*"` | `/webhooks/github/push`      | `/webhook/`     |
| `r"/health$"`     | `/health`                    | `/health-check` |

## Trusted origins

You can allow requests from specific external origins that you trust completely.

```python
# app/settings.py
CSRF_TRUSTED_ORIGINS = [
    "https://api.example.com",
    "https://mobile.example.com:8443",
    "https://trusted-partner.com",
]
```

Each origin should be a full URL with scheme (e.g., `https://example.com`). Include the port if it's non-standard.

**Warning**: Trusted origins bypass all CSRF protection. Only add origins you completely control or trust, as they can make requests that appear to come from your users.

## FAQs

#### Why does Plain use Sec-Fetch-Site instead of CSRF tokens?

Token-based CSRF protection requires embedding tokens in forms and validating them on the server. This adds complexity to your templates and requires careful handling of token rotation. Modern browsers provide the `Sec-Fetch-Site` header which tells the server whether a request is same-origin, making tokens unnecessary. The header approach is simpler, more reliable, and cannot be leaked through XSS vulnerabilities like tokens can.

#### What about HTTP sites during development?

The `Sec-Fetch-Site` header is only sent by browsers to HTTPS and localhost origins. For development on localhost, CSRF protection works normally. For HTTP origins on other hosts, the middleware falls back to `Origin` header validation.

#### Why are same-site requests (like subdomains) blocked?

Plain uses same-origin protection rather than same-site protection. Subdomains can have different trust levels than your main domain. For example, `user-content.example.com` should not be able to make authenticated requests to `app.example.com`. If you need to allow requests from a subdomain, add it to `CSRF_TRUSTED_ORIGINS`.

#### How do I debug CSRF rejections?

When a request is rejected, the middleware raises a `SuspiciousOperationError400` with a detailed message explaining why. Check your server logs for messages like "CSRF rejected: Cross-origin request from Sec-Fetch-Site: cross-site" to understand the cause.

## Installation

This module is included with the `plain` package and enabled by default. No additional installation or configuration is required.

The middleware is automatically added to the request handling pipeline through [`BUILTIN_BEFORE_MIDDLEWARE`](../internal/handlers/base.py#BUILTIN_BEFORE_MIDDLEWARE).
