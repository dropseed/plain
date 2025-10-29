# plain.observer

**On-page telemetry and observability tools for Plain.**

- [Installation](#installation)
- [Content Security Policy (CSP)](#content-security-policy-csp)

## Installation

Install the `plain.observer` package from [PyPI](https://pypi.org/project/plain.observer/):

```bash
uv add plain.observer
```

Add `plain.observer` to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.observer",
]
```

Include the observer URLs in your URL configuration:

```python
# app/urls.py
from plain.observer.urls import ObserverRouter
from plain.urls import Router, include

class AppRouter(Router):
    namespace = ""
    urls = [
        # ...
        include("observer/", ObserverRouter),
    ]
```

Run migrations to create the necessary database tables:

```bash
plain migrate
```

After installation, Observer will automatically integrate with your application's toolbar (if using `plain.admin`). You can access the web interface at `/observer/traces/` or use the CLI commands to analyze traces.

## Content Security Policy (CSP)

If you're using a Content Security Policy (CSP), the Observer toolbar panel requires `frame-ancestors 'self'` to display trace information in an iframe.

Without this directive, the toolbar panel will fail to load with a CSP error: `"Refused to frame... because an ancestor violates the following Content Security Policy directive: 'frame-ancestors 'none'"`.

Example CSP configuration:

```python
DEFAULT_RESPONSE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{request.csp_nonce}'; "
        "style-src 'self' 'nonce-{request.csp_nonce}'; "
        "frame-ancestors 'self'; "  # Required for Observer toolbar
        # ... other directives
    ),
}
```
