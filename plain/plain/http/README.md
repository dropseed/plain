# HTTP

**Request and response handling for Plain applications.**

- [Overview](#overview)
- [Request](#request)
    - [Headers](#headers)
    - [Query parameters](#query-parameters)
    - [Body data](#body-data)
    - [Content negotiation](#content-negotiation)
    - [Cookies](#cookies)
- [Response](#response)
    - [Response types](#response-types)
    - [Setting cookies](#setting-cookies)
    - [Default response headers](#default-response-headers)
- [Content Security Policy (CSP)](#content-security-policy-csp)
- [Middleware](#middleware)
- [Exceptions](#exceptions)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You interact with [`Request`](./request.py#Request) and [`Response`](./response.py#Response) objects in your views and middleware.

```python
from plain.views import View
from plain.http import Response

class ExampleView(View):
    def get(self):
        # Access a request header
        user_agent = self.request.headers.get("User-Agent")

        # Access a query parameter
        page = self.request.query_params.get("page", "1")

        # Create and return a response
        response = Response("Hello, world!", status_code=200)
        response.headers["X-Custom-Header"] = "Custom Value"
        return response
```

## Request

The [`Request`](./request.py#Request) object provides access to all incoming HTTP request data.

### Headers

Access request headers through the `headers` property. Header names are case-insensitive.

```python
content_type = self.request.headers.get("Content-Type")
auth = self.request.headers.get("authorization")  # Case-insensitive
```

### Query parameters

Query string parameters are available as a [`QueryDict`](./request.py#QueryDict) through `query_params`.

```python
# URL: /search?q=plain&page=2
query = self.request.query_params.get("q")  # "plain"
page = self.request.query_params.get("page", "1")  # "2"

# For parameters with multiple values (?tags=python&tags=web)
tags = self.request.query_params.getlist("tags")  # ["python", "web"]
```

### Body data

Access request body data based on the content type.

**JSON data:**

```python
# Returns dict, raises BadRequestError400 for invalid JSON
data = self.request.json_data
name = data.get("name")
```

**Form data:**

```python
# For application/x-www-form-urlencoded or multipart/form-data
form = self.request.form_data
email = form.get("email")
```

**File uploads:**

```python
# For multipart/form-data requests
uploaded_file = self.request.files.get("document")
if uploaded_file:
    content = uploaded_file.read()
```

**Raw body:**

```python
raw_bytes = self.request.body
```

### Content negotiation

Check what content types the client accepts.

```python
# Check if client accepts JSON
if self.request.accepts("application/json"):
    return JsonResponse({"message": "Hello"})

# Get preferred type from options
preferred = self.request.get_preferred_type("text/html", "application/json")
```

### Cookies

Read cookies from the request.

```python
session_id = self.request.cookies.get("session_id")

# Read a signed cookie (returns None if signature is invalid)
user_id = self.request.get_signed_cookie("user_id", default=None)
```

## Response

The [`Response`](./response.py#Response) class creates HTTP responses with string or bytes content.

```python
from plain.http import Response

# Basic response
response = Response("Hello, world!")

# With status code and headers
response = Response(
    content="Created!",
    status_code=201,
    headers={"X-Custom": "value"},
)

# Set content type
response = Response("<h1>Hello</h1>", content_type="text/html")
```

### Response types

Plain provides specialized response classes for common use cases.

**JSON responses:**

```python
from plain.http import JsonResponse

return JsonResponse({"name": "Plain", "version": "1.0"})
```

**Redirects:**

```python
from plain.http import RedirectResponse

return RedirectResponse("/new-location")
```

**File downloads:**

```python
from plain.http import FileResponse

# Serve a file
return FileResponse(open("report.pdf", "rb"))

# Force download with custom filename
return FileResponse(
    open("report.pdf", "rb"),
    as_attachment=True,
    filename="monthly-report.pdf",
)
```

**Streaming responses:**

```python
from plain.http import StreamingResponse

def generate_data():
    for i in range(1000):
        yield f"Line {i}\n"

return StreamingResponse(generate_data(), content_type="text/plain")
```

Other response types include [`NotModifiedResponse`](./response.py#NotModifiedResponse) (304) and [`NotAllowedResponse`](./response.py#NotAllowedResponse) (405).

### Setting cookies

Set cookies on the response.

```python
response = Response("Welcome!")
response.set_cookie("session_id", "abc123", httponly=True, secure=True)

# With expiration
response.set_cookie("remember_me", "yes", max_age=86400 * 30)  # 30 days

# Signed cookie (tamper-proof)
response.set_signed_cookie("user_id", "42", httponly=True)

# Delete a cookie
response.delete_cookie("old_cookie")
```

### Default response headers

Plain applies default headers from `DEFAULT_RESPONSE_HEADERS` in settings to all responses. You can customize these per-view.

**Override a default header:**

```python
response = Response("content")
response.headers["X-Frame-Options"] = "SAMEORIGIN"
```

**Remove a default header:**

```python
response = Response("content")
response.headers["X-Frame-Options"] = None  # Removes the header
```

**Extend a default header:**

```python
from plain.runtime import settings

if csp := settings.DEFAULT_RESPONSE_HEADERS.get("Content-Security-Policy"):
    csp = csp.format(request=self.request)
    response.headers["Content-Security-Policy"] = f"{csp}; script-src https://cdn.example.com"
```

## Content Security Policy (CSP)

Plain includes built-in support for Content Security Policy through nonces. Each request generates a unique cryptographically secure nonce available via `request.csp_nonce`.

**Configure CSP in settings:**

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
    "X-Frame-Options": "DENY",
}
```

The `{request.csp_nonce}` placeholder is replaced with a unique nonce for each request.

**Use nonces in templates:**

```html
<script nonce="{{ request.csp_nonce }}">
    console.log("This script is allowed by CSP");
</script>

<style nonce="{{ request.csp_nonce }}">
    .example { color: red; }
</style>
```

External scripts and stylesheets loaded from `'self'` don't need nonces:

```html
<script src="/assets/app.js"></script>
<link rel="stylesheet" href="/assets/app.css">
```

Use [Google's CSP Evaluator](https://csp-evaluator.withgoogle.com/) to analyze your CSP policy.

## Middleware

Create custom middleware by subclassing [`HttpMiddleware`](./middleware.py#HttpMiddleware).

```python
from plain.http import HttpMiddleware, Request, Response

class TimingMiddleware(HttpMiddleware):
    def process_request(self, request: Request) -> Response:
        import time
        start = time.time()

        response = self.get_response(request)

        duration = time.time() - start
        response.headers["X-Request-Duration"] = f"{duration:.3f}s"
        return response
```

## Exceptions

Raise exceptions to return specific HTTP error responses.

```python
from plain.http import NotFoundError404, ForbiddenError403, BadRequestError400

# Return 404
raise NotFoundError404("Page not found")

# Return 403
raise ForbiddenError403("Access denied")

# Return 400
raise BadRequestError400("Invalid input")
```

Additional exceptions include [`SuspiciousOperationError400`](./exceptions.py#SuspiciousOperationError400), [`TooManyFieldsSentError400`](./exceptions.py#TooManyFieldsSentError400), [`TooManyFilesSentError400`](./exceptions.py#TooManyFilesSentError400), and [`RequestDataTooBigError400`](./exceptions.py#RequestDataTooBigError400).

## FAQs

#### How do I access the client's IP address?

Use `request.client_ip`. If you're behind a proxy, enable `HTTP_X_FORWARDED_FOR` in settings.

```python
ip = self.request.client_ip
```

#### How do I build an absolute URL?

Use `request.build_absolute_uri()`.

```python
# Current page
url = self.request.build_absolute_uri()

# Specific path
url = self.request.build_absolute_uri("/api/users")
```

#### How do I check if the request is HTTPS?

Use `request.is_https()` or check `request.scheme`.

```python
if self.request.is_https():
    # Secure connection
    pass
```

#### What's the difference between QueryDict and a regular dict?

[`QueryDict`](./request.py#QueryDict) handles multiple values for the same key (common in query strings and form data). Use `get()` for a single value or `getlist()` for all values.

#### How do I handle large file uploads?

Configure `DATA_UPLOAD_MAX_MEMORY_SIZE` in settings. For very large files, consider streaming the upload instead of loading it into memory.

## Installation

The `plain.http` module is included with Plain by default. No additional installation is required.

```python
from plain.http import Request, Response, JsonResponse
```
