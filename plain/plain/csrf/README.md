# CSRF

**Cross-Site Request Forgery (CSRF) protection using modern request headers.**

- [Overview](#overview)
- [Usage](#usage)
- [CSRF Exempt Paths](#csrf-exempt-paths)
- [Trusted Origins](#trusted-origins)

## Overview

Plain provides modern CSRF protection based on [Filippo Valsorda's 2025 research](https://words.filippo.io/csrf/) using `Sec-Fetch-Site` headers and origin validation.

## Usage

The `CsrfViewMiddleware` is [automatically installed](../internal/handlers/base.py#BUILTIN_BEFORE_MIDDLEWARE) and works transparently. **No changes to your forms or templates are needed.**

## CSRF Exempt Paths

In some cases, you may need to disable CSRF protection for specific paths (like API endpoints or webhooks). Configure exempt paths using regex patterns in your settings:

```python
# settings.py
CSRF_EXEMPT_PATHS = [
    r"^/api/",             # All API endpoints
    r"^/api/v\d+/",        # Versioned APIs: /api/v1/, /api/v2/, etc.
    r"/webhooks/.*",       # All webhook paths
    r"/webhooks/github/",  # Specific webhook
    r"/health$",           # Exact match for /health endpoint
]
```

**Pattern Matching**: Exempt paths use Python regex patterns with `re.search()` against the full URL path including the leading slash.

**Examples:**

- `r"^/api/"` - matches `/api/users/`, `/api/posts/`
- `r"/webhooks/.*"` - matches `/webhooks/github/push`, `/webhooks/stripe/payment`
- `r"/health$"` - matches `/health` but not `/health-check`
- `r"^/api/v\d+/"` - matches `/api/v1/users/`, `/api/v2/posts/`

**Common Use Cases:**

```python
CSRF_EXEMPT_PATHS = [
    # API endpoints (often consumed by JavaScript/mobile apps)
    r"^/api/",

    # Webhooks (external services posting data)
    r"/webhooks/.*",

    # Health checks and monitoring
    r"/health$",
    r"/status$",
    r"/metrics$",

    # File uploads (if using direct POST)
    r"/upload/",
]
```

## Trusted Origins

In some cases, you may need to allow requests from specific external origins (like API clients or mobile apps). You can configure trusted origins in your settings:

```python
# settings.py
CSRF_TRUSTED_ORIGINS = [
    "https://api.example.com",
    "https://mobile.example.com:8443",
    "https://trusted-partner.com",
]
```

**Important**: Trusted origins bypass **all** CSRF protection. Only add origins you completely trust, as they can make requests that appear to come from your users.
