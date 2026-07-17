# plain.test

**The test-authoring vocabulary — everything a test file imports.**

- [Overview](#overview)
- [Making requests](#making-requests)
    - [GET requests](#get-requests)
    - [POST requests](#post-requests)
    - [Other HTTP methods](#other-http-methods)
    - [Following redirects](#following-redirects)
    - [Custom headers](#custom-headers)
- [Inspecting responses](#inspecting-responses)
- [Authentication](#authentication)
- [Sessions](#sessions)
- [Expected exceptions](#expected-exceptions)
- [Test metadata](#test-metadata)
- [Overriding context](#overriding-context)
- [Capturing OpenTelemetry signals](#capturing-opentelemetry-signals)
- [RequestFactory](#requestfactory)
- [Test lifecycles](#test-lifecycles)
- [FAQs](#faqs)
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

Tests are run by [`plain.testing`](../../../plain-testing/plain/testing/README.md) — the `plain test` command. This module is the authoring side: the client, the assertion helpers, the declarative decorators, and the context managers your test files import.

## Making requests

The client speaks the same vocabulary as the rest of Plain: `form_data=` arrives as `request.form_data`, `json_data=` as `request.json_data`, `files=` as `request.files`, and `query_params=` as `request.query_params`. Everything after the path is keyword-only.

### GET requests

```python
response = client.get("/search/", query_params={"q": "hello"})
```

### POST requests

Send a form:

```python
response = client.post("/submit/", form_data={"name": "Alice", "email": "alice@example.com"})
```

Send JSON — the value is serialized for you:

```python
response = client.post("/api/users/", json_data={"name": "Alice"})
```

Send file uploads alongside form fields:

```python
response = client.post("/upload/", form_data={"title": "Report"}, files={"file": file_obj})
```

Send a raw body with an explicit content type:

```python
response = client.post("/webhooks/", body=payload_bytes, content_type="application/xml")
```

### Other HTTP methods

The client supports all standard HTTP methods: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, and `trace`. The body-carrying methods take the same arguments as `post`.

```python
response = client.put("/api/users/1/", json_data={"name": "Bob"})
response = client.delete("/api/users/1/")
```

### Following redirects

Redirects aren't followed unless you ask — where a request lands is usually the thing worth asserting.

```python
response = client.post("/signup/", form_data={"email": "a@example.com"})
assert response.redirect_to == "/welcome/"
```

Set `follow_redirects=True` to follow the chain to its destination:

```python
response = client.get("/old-url/", follow_redirects=True)
assert response.status_code == 200  # Final destination
assert response.redirect_chain == [("/new-url/", 302)]
```

### Custom headers

```python
response = client.get("/api/", headers={"Authorization": "Bearer token123"})
```

You can also set default headers when creating the client.

```python
client = Client(headers={"Accept-Language": "en-US"})
```

## Inspecting responses

Responses are data, not assertion methods — bare `assert` is the assertion API. The [`ClientResponse`](./client.py#ClientResponse) wrapper provides:

- `status_code` — HTTP status code
- `headers` — response headers
- `text` — content decoded as a string
- `body` — raw content bytes (`content` also works)
- `json_data` — content parsed as JSON (requires a JSON content type)
- `redirect_to` — the redirect target on a 3xx response, `None` otherwise
- `request` — the request that produced this response, after middleware ran
- `redirect_chain` — list of `(url, status_code)` pairs when following redirects
- `resolver_match` — the resolved URL route

```python
response = client.get("/api/users/")
assert response.json_data["users"][0]["name"] == "Alice"
```

By default, the client re-raises unhandled view exceptions so failures point at the real error. Pass `Client(raise_request_exception=False)` to get the 500 response instead.

## Authentication

Log a user in without going through the login form:

```python
client.force_login(user)
response = client.get("/dashboard/")
assert response.status_code == 200

client.logout()
assert client.get("/dashboard/").redirect_to == "/login/"
```

To check who was authenticated for a request, combine `response.request` with [plain.auth](../../../plain-auth/plain/auth/README.md)'s helpers:

```python
from plain.auth.requests import get_request_user

assert get_request_user(response.request) == user
```

## Sessions

`client.session` exposes the current session (requires [plain.sessions](../../../plain-sessions/plain/sessions/README.md)):

```python
assert client.session["cart_id"] == cart.id
```

## Expected exceptions

Use [`raises`](./raises.py#raises) to assert that a block raises:

```python
from plain.test import raises


def test_invalid_email():
    with raises(ValidationError) as caught:
        validate_email("nope")
    assert "email" in str(caught.exception)
```

Pass `match=` to also require the message to match a regex.

## Test metadata

Decorators declare static facts about a test — they never inject runtime values:

```python
from plain.test import cases, skip, tag


@cases(
    ("a@example.com", True),
    ("nope", False),
)
def test_email_validation(email, valid):
    assert is_valid_email(email) is valid


@skip("Waiting on the new billing API")
def test_invoice_totals(): ...


@tag("slow")
def test_big_import(): ...
```

- [`cases`](./decorators.py#cases) — each tuple becomes its own test run
- [`skip`](./decorators.py#skip) — always skipped, reason shown in the report
- [`tag`](./decorators.py#tag) — labels for selection (`plain test --tag slow`)

## Overriding context

Runtime state changes are context managers, so their scope is visible as indentation:

```python
from plain.test import override_settings, patch


def test_debug_error_page():
    with override_settings(DEBUG=True):
        response = Client().get("/broken/")


def test_external_call():
    with patch(billing, "charge_card", lambda **kwargs: "ch_123"):
        checkout(cart)
```

- [`override_settings`](./overrides.py#override_settings) — set Plain settings for the block, restored on exit
- [`patch`](./overrides.py#patch) — replace an attribute (or a mapping key, e.g. `os.environ`) for the block

## Capturing OpenTelemetry signals

```python
from opentelemetry import trace

from plain.test import capture_spans


def test_homepage_span():
    with capture_spans() as spans:
        Client().get("/")

    server_span = spans.find(kind=trace.SpanKind.SERVER)
    assert server_span.attributes["http.route"] == "/"
```

[`capture_spans`](./otel.py#capture_spans) yields the spans emitted during the block (`.get_finished_spans()`, `.find(kind=..., name=...)`). [`capture_metrics`](./otel.py#capture_metrics) yields the metrics — `.points(name)` returns every data point recorded for a metric, `.collect()` forces observable callbacks, `.clear()` forgets what's been captured so far.

## RequestFactory

[`RequestFactory`](./client.py#RequestFactory) builds `Request` objects without sending them — useful for testing middleware or request handling in isolation. It takes the same keyword arguments as the client methods.

```python
from plain.test import RequestFactory

request = RequestFactory().get("/hello/", query_params={"name": "Alice"})
```

## Test lifecycles

[`TestLifecycle`](./lifecycle.py#TestLifecycle) is the protocol packages implement to participate in test runs — [plain.postgres](../../../plain-postgres/plain/postgres/README.md) wraps each test in a rolled-back transaction, [plain.email](../../../plain-email/plain/email/README.md) resets the outbox. Implementations register under the `plain.testing` entry point group and are driven by the runner; packages never import the runner.

## FAQs

#### What is the difference between Client and RequestFactory?

`Client` sends the request through the full middleware and view pipeline and returns the response. `RequestFactory` only constructs the `Request` object — you call the view or middleware yourself.

#### How do I test file uploads?

Pass file-like objects via `files={...}` — they're encoded into a multipart body together with `form_data`.

#### Where are the database and email helpers?

Package-specific helpers live with their packages: `plain.postgres.test` (`isolated_db`, `capture_queries`, `max_queries`), `plain.email.test` (`outbox`). `plain.test` holds only the framework-generic vocabulary.

## Installation

`plain.test` ships with Plain — no installation needed. To run tests, add the [plain.testing](../../../plain-testing/plain/testing/README.md) dev dependency:

```bash
uv add plain.testing --dev
```
