# HTTP

**HTTP request and response handling.**

- [Overview](#overview)
- [Content Security Policy (CSP)](#content-security-policy-csp)
- [Customizing Default Response Headers](#customizing-default-response-headers)

## Overview

Typically you will interact with [Request](request.py#Request) and [Response](response.py#ResponseBase) objects in your views and middleware.

```python
from plain.views import View
from plain.http import Response

class ExampleView(View):
    def get(self):
        # Accessing a request header
        print(self.request.headers.get("Example-Header"))

        # Accessing a query parameter
        print(self.request.query_params.get("example"))

        # Creating a response
        response = Response("Hello, world!", status_code=200)

        # Setting a response header
        response.headers["Example-Header"] = "Example Value"

        return response
```

## Content Security Policy (CSP)

Plain includes built-in support for Content Security Policy (CSP) through nonces, allowing you to use strict CSP policies without `'unsafe-inline'`.

Each request generates a unique cryptographically secure nonce available via [`request.csp_nonce`](request.py#Request.csp_nonce):

### Configuring CSP Headers

Include CSP in `DEFAULT_RESPONSE_HEADERS` using `{request.csp_nonce}` placeholders for dynamic nonces:

```python
# app/settings.py
DEFAULT_RESPONSE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{request.csp_nonce}'; "
        "style-src 'self' 'nonce-{request.csp_nonce}'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
    # Other default headers...
    "X-Frame-Options": "DENY",
}
```

The `{request.csp_nonce}` placeholder will be replaced with a unique nonce for each request.

Use tools like [Google's CSP Evaluator](https://csp-evaluator.withgoogle.com/) to analyze your CSP policy and identify potential security issues or misconfigurations.

### Using Nonces in Templates

Add the nonce attribute to inline scripts and styles in your templates:

```html
<!-- Inline script with nonce -->
<script nonce="{{ request.csp_nonce }}">
    console.log("This script is allowed by CSP");
</script>

<!-- Inline style with nonce -->
<style nonce="{{ request.csp_nonce }}">
    .example { color: red; }
</style>
```

External scripts and stylesheets loaded from `'self'` don't need nonces:

```html
<!-- External scripts/styles work with 'self' directive -->
<script src="/assets/app.js"></script>
<link rel="stylesheet" href="/assets/app.css">
```

## Customizing Default Response Headers

Plain applies default response headers to all responses via `DEFAULT_RESPONSE_HEADERS` in settings. Views can customize these headers in several ways:

### Override Default Headers

Set the header to a different value in your view:

```python
class MyView(View):
    def get(self):
        response = Response("content")
        # Override the default X-Frame-Options: DENY
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response
```

### Remove Default Headers

Set the header to `None` to prevent it from being applied:

```python
class EmbeddableView(View):
    def get(self):
        response = Response("content")
        # Remove X-Frame-Options entirely to allow embedding
        response.headers["X-Frame-Options"] = None
        return response
```

### Extend Default Headers

Read the default value from settings, modify it, then set it in your view:

```python
from plain.runtime import settings

class MyView(View):
    def get(self):
        response = Response("content")

        # Get the default CSP policy
        if csp := settings.DEFAULT_RESPONSE_HEADERS.get("Content-Security-Policy"):
            # Format it with the current request to resolve placeholders
            csp = csp.format(request=self.request)
            # Extend with additional sources
            response.headers["Content-Security-Policy"] = (
                f"{csp}; script-src https://analytics.example.com"
            )

        return response
```
