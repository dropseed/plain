# plain.test

**Testing utilities for making HTTP requests and inspecting responses.**

- [Overview](#overview)
- [Making requests](#making-requests)
    - [GET requests](#get-requests)
    - [POST requests](#post-requests)
    - [Other HTTP methods](#other-http-methods)
    - [Following redirects](#following-redirects)
    - [Custom headers](#custom-headers)
- [Inspecting responses](#inspecting-responses)
    - [JSON responses](#json-responses)
    - [Response attributes](#response-attributes)
- [Authentication](#authentication)
- [Sessions](#sessions)
- [RequestFactory](#requestfactory)
- [FAQs](#faqs)
    - [What is the difference between Client and RequestFactory?](#what-is-the-difference-between-client-and-requestfactory)
    - [How do I test file uploads?](#how-do-i-test-file-uploads)
    - [How do I disable exception raising?](#how-do-i-disable-exception-raising)
- [Installation](#installation)

## Overview

You can test your Plain views using the [`Client`](./client.py#Client) class. It simulates HTTP requests and returns responses, allowing you to verify status codes, content, and behavior without running a real server.

```python
from plain.test import Client


def test_homepage():
    client = Client()
    response = client.get("/")
    assert response.status_code == 200
```

The client maintains cookies and session state across requests, so you can test multi-step flows like login and logout.

## Making requests

### GET requests

Pass query parameters using the `data` argument.

```python
response = client.get("/search/", data={"q": "hello"})
```

### POST requests

Send form data by default.

```python
response = client.post("/submit/", data={"name": "Alice", "email": "alice@example.com"})
```

Send JSON by setting the content type.

```python
response = client.post(
    "/api/users/",
    data={"name": "Alice"},
    content_type="application/json",
)
```

### Other HTTP methods

The client supports all standard HTTP methods: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, and `trace`.

```python
response = client.put("/api/users/1/", data={"name": "Bob"}, content_type="application/json")
response = client.patch("/api/users/1/", data={"name": "Bob"}, content_type="application/json")
response = client.delete("/api/users/1/")
```

### Following redirects

Set `follow=True` to automatically follow redirect responses.

```python
response = client.get("/old-url/", follow=True)
assert response.status_code == 200  # Final destination
assert response.redirect_chain == [("/new-url/", 302)]
```

### Custom headers

Pass headers using the `headers` argument.

```python
response = client.get("/api/", headers={"Authorization": "Bearer token123"})
```

You can also set default headers when creating the client.

```python
client = Client(headers={"Accept-Language": "en-US"})
```

## Inspecting responses

### JSON responses

Parse JSON response content using the `json()` method.

```python
response = client.get("/api/users/")
data = response.json()
assert data["users"][0]["name"] == "Alice"
```

### Response attributes

The [`ClientResponse`](./client.py#ClientResponse) wrapper provides access to:

- `status_code` - HTTP status code (200, 404, etc.)
- `content` - Response body as bytes
- `headers` - Response headers
- `cookies` - Cookies set by the response
- `wsgi_request` - The original request object
- `resolver_match` - URL resolver match information
- `redirect_chain` - List of redirects when using `follow=True`

## Authentication

You can log in a user without going through the login flow using `force_login`. This requires `plain.auth` to be installed.

```python
user = User.objects.get(username="alice")
client.force_login(user)
response = client.get("/dashboard/")
assert response.status_code == 200
```

Log out using the `logout` method.

```python
client.logout()
response = client.get("/dashboard/")
assert response.status_code == 302  # Redirected to login
```

## Sessions

Access session data using the `session` property. This requires `plain.sessions` to be installed.

```python
client.session["cart_id"] = "abc123"
response = client.get("/cart/")
assert "abc123" in response.content.decode()
```

## RequestFactory

Use [`RequestFactory`](./client.py#RequestFactory) to create request objects directly without going through the WSGI handler. This is useful for testing views in isolation.

```python
from plain.test import RequestFactory

rf = RequestFactory()
request = rf.get("/hello/")
response = my_view(request)
assert response.status_code == 200
```

The factory supports the same HTTP methods as the client: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, and `trace`.

## FAQs

#### What is the difference between Client and RequestFactory?

The `Client` executes requests through the full middleware stack and maintains state (cookies, sessions) between requests. Use it for integration tests.

The `RequestFactory` creates request objects without executing them. Use it for unit testing individual views in isolation.

#### How do I test file uploads?

Pass file-like objects in the `data` dictionary.

```python
from io import BytesIO

file = BytesIO(b"file contents")
file.name = "test.txt"
response = client.post("/upload/", data={"file": file})
```

#### How do I disable exception raising?

By default, the client raises exceptions that occur during request processing. Set `raise_request_exception=False` to capture them on the response instead.

```python
client = Client(raise_request_exception=False)
response = client.get("/broken/")
assert response.status_code == 500
```

## Installation

The `plain.test` module is included with the `plain` package. No additional installation is required.

For additional testing utilities like pytest fixtures and browser testing, see [`plain.pytest`](/plain-pytest/README.md).
