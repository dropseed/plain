# CSRF

**Cross-Site Request Forgery (CSRF) protection using modern request headers.**

- [Overview](#overview)
- [Usage](#usage)
- [CSRF Exempt Views](#csrf-exempt-views)
- [Trusted Origins](#trusted-origins)

## Overview

Plain provides modern CSRF protection based on [Filippo Valsorda's 2025 research](https://words.filippo.io/csrf/) using `Sec-Fetch-Site` headers and origin validation.

## Usage

The `CsrfViewMiddleware` is [automatically installed](../internal/handlers/base.py#BUILTIN_BEFORE_MIDDLEWARE) and works transparently. **No changes to your forms or templates are needed.**

## CSRF Exempt Views

In some cases, you may need to disable CSRF protection for specific views (such as API endpoints or webhooks). Plain provides a mixin for class-based views.

```python
from plain.views import View
from plain.views.csrf import CsrfExemptViewMixin


class WebhookView(CsrfExemptViewMixin, View):
    """API webhook that needs to accept POST requests without CSRF protection."""

    def post(self):
        # Process webhook data
        return {"status": "received"}
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
