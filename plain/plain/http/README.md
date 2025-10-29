# HTTP

**HTTP request and response handling.**

- [Overview](#overview)
- [Content Security Policy (CSP)](#content-security-policy-csp)

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

Set `DEFAULT_RESPONSE_HEADERS` as a callable function to generate dynamic CSP headers with nonces:

```python
# app/settings.py
def DEFAULT_RESPONSE_HEADERS(request):
    """
    Dynamic response headers with CSP nonces.
    """
    nonce = request.csp_nonce
    return {
        "Content-Security-Policy": (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'nonce-{nonce}'; "
            f"img-src 'self' data:; "
            f"font-src 'self'; "
            f"connect-src 'self'; "
            f"frame-ancestors 'self'; "
            f"base-uri 'self'; "
            f"form-action 'self'"
        ),
    }
```

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
