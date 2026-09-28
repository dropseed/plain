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
    - [Streaming responses](#streaming-responses)
- [Authentication](#authentication)
- [Sessions](#sessions)
- [Expected exceptions](#expected-exceptions)
- [Test metadata](#test-metadata)
    - [Skipping from inside a test](#skipping-from-inside-a-test)
- [Overriding context](#overriding-context)
- [Capturing OpenTelemetry signals](#capturing-opentelemetry-signals)
- [Capturing log records](#capturing-log-records)
- [WebSockets](#websockets)
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
response = client.post(
    "/submit/", form_data={"name": "Alice", "email": "alice@example.com"}
)
```

A form is urlencoded, and becomes multipart only when `files=` is given — the same choice a browser makes, so the view under test sees the content type it will see in production.

Send JSON — the value is serialized for you:

```python
response = client.post("/api/users/", json_data={"name": "Alice"})
```

Send file uploads alongside form fields:

```python
response = client.post(
    "/upload/", form_data={"title": "Report"}, files={"file": file_obj}
)
```

Send a raw body with an explicit content type:

```python
response = client.post("/webhooks/", body=payload_bytes, content_type="application/xml")
```

### Other HTTP methods

The client supports all standard HTTP methods: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, and `trace`. The body-carrying methods take the same arguments as `post`.

```python
response = client.put("/api/users/1/", json_data={"name": "Bob"})
response = client.patch("/api/users/1/", json_data={"name": "Bob"})
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

- `status_code` — the status that went out
- `headers` — response headers
- `body` — the bytes the response sent
- `text` — the body decoded as a string
- `json_data` — the body parsed as JSON (requires a JSON content type)
- `redirect_to` — the redirect target on a 3xx response, `None` otherwise
- `request` — the request that produced this response, after middleware ran
- `redirect_chain` — list of `(url, status_code)` pairs when following redirects
- `resolver_match` — the resolved URL route

```python
response = client.get("/api/users/")
assert response.json_data["users"][0]["name"] == "Alice"
```

By default, the client re-raises unhandled view exceptions so failures point at the real error. Pass `Client(raise_request_exception=False)` to get the 500 response instead.

### Streaming responses

The client reads a streaming body to the end before it returns, the way a server sends it, so `body` (and `text`, `json_data`) hold what a `StreamingResponse`, `FileResponse`, or `AsyncStreamingResponse` sent:

```python
response = client.get("/export.csv")
assert response.body.startswith(b"id,name")
```

The response itself stays what the view returned (a `FileResponse` is still one). Because the whole body is read, a stream that never ends (an endless event feed) makes the request never return — test those views' pieces directly instead. HEAD requests and bodiless statuses (204, 304) never read the body.

If a body raises partway through, the error is re-raised from the request unless the client was created with `raise_request_exception=False`, in which case `response.exception` holds it and `body` has what came before. A body that fails before producing anything is answered with a 500, as a server would, and `status_code` says so.

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

`caught.exception` is typed as the exception class you asked for, so its own attributes are reachable without a cast (`caught.exception.messages` on a `ValidationError`). It's readable only after the block exits — inside the block nothing has been caught yet, and reading it says so rather than handing back a `None`.

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

`@cases` is the only way a test takes parameters. Nothing is passed to a test by name, so a test whose parameters no case fills is rejected when the file is collected, with a message naming the test and the parameters.

Cases are reported by position — `test_email_validation[0]`, `[1]`. Wrap one in [`case`](./decorators.py#case) to name it instead:

```python
from plain.test import case, cases


@cases(
    case("a@example.com", True, id="plain address"),
    case("nope", False, id="no at sign"),
)
def test_email_validation(email, valid):
    assert is_valid_email(email) is valid
```

That reports as `test_email_validation[no at sign]`, and the re-run command in the failure output names the case. The id sits on the case it names, so adding or reordering cases can't shift the names onto the wrong values.

A test takes one `@cases`. A second one raises instead of replacing the first. For every combination of two lists, pass the combinations:

```python
import itertools

from plain.test import cases


@cases(*itertools.product(["kwargs", "object"], ["insert", "update"]))
def test_write_paths(source, operation): ...
```

### Skipping from inside a test

`@skip` is for a test that never runs. When only the running test can tell, call [`skip_test`](./skipping.py#skip_test) in its body:

```python
from plain.test import cases, skip_test


@cases("text", "encrypted")
def test_field_supports_contains(kind):
    if kind == "encrypted":
        skip_test("Encrypted fields have no substring match")
    assert "contains" in lookups_for(kind)
```

The test stops there and is reported as skipped, with the reason. Everything it entered still exits: `with` blocks unwind and the database transaction is rolled back. An `except Exception:` around the call doesn't swallow the skip.

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

`patch` takes the object and the attribute name, not a dotted string. On exit a class gets back exactly what it held: a `staticmethod` is still one, and an attribute the class only inherited is inherited again.

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

What they yield is importable for annotating your own helpers: `CapturedSpans` and `CapturedMetrics`.

```python
from plain.test import CapturedSpans


def route_of(spans: CapturedSpans) -> str:
    return spans.find(kind=trace.SpanKind.SERVER).attributes["http.route"]
```

## Capturing log records

```python
from plain.test import Client, capture_logs


def test_server_error_is_logged():
    with capture_logs() as logs:
        Client(raise_request_exception=False).get("/broken/")

    assert "Server error" in logs.messages
    assert logs[0].path == "/broken/"
```

[`capture_logs`](./logs.py#capture_logs) yields the records emitted during the block. It behaves like a list of `logging.LogRecord`, plus `.messages` for the formatted messages. Structured context passed as `context={...}` lands on the record as ordinary attributes, so `logs[0].path` reads it back.

With no arguments it captures the whole `plain` and `app` trees; name loggers to narrow it (`capture_logs("plain.jobs")`). Plain's loggers don't propagate to the root logger, so attaching a handler there would see nothing — this attaches to the named loggers directly, lowers their level for the block, and restores everything on exit.

`.span_context_for(message)` returns the OpenTelemetry span context that was current when that record was emitted. That's the check behind "this exception log landed _inside_ its error span" — a record emitted with no span current exports with empty trace/span ids, and the one failure gets reported twice downstream (the span's exception event plus an orphaned error log):

```python
from plain.test import capture_logs, capture_spans


def test_claim_failure_log_is_correlated():
    with capture_spans() as spans, capture_logs("plain.jobs") as logs:
        run_the_failing_claim()

    span = spans.find(name="claim job")
    assert logs.span_context_for("Failed to claim job").trace_id == (
        span.context.trace_id
    )
```

## WebSockets

`Client.websocket()` runs the handshake through the same pipeline as any request (cookies and auth included), then drives the view's `websocket()` in-process:

```python
from plain.test import Client, WebSocketRejected, raises


def test_echo():
    with Client().websocket("/live/", subprotocols=("binary",)) as ws:
        assert ws.subprotocol == "binary"
        ws.send("hello")
        assert ws.receive() == "echo: hello"


def test_login_required():
    with raises(WebSocketRejected) as caught:
        Client().websocket("/live/")
    assert caught.exception.response.status_code == 403
```

It takes `query_params=`, `headers=`, and `secure=` like `get()`, plus `subprotocols=` and `timeout=`.

- `ws.send(message)` sends one message to the view; `ws.receive()` returns the next one it sends.
- `ws.close(code=1000, reason="")` closes from the client side and waits for the view to finish. Leaving the `with` block closes it if the test didn't.
- `ws.subprotocol` is the negotiated subprotocol and `ws.response` is the 101 itself, for asserting on its headers and cookies.
- Every call has a timeout (5 seconds by default, `receive(timeout=...)` per call) and raises `TimeoutError` when it elapses.
- An exception raised by the view surfaces from `receive()` and again when the `with` block exits; a view that closes the socket makes `receive()` raise `WebSocketClosed` with its code and reason.
- A handshake that doesn't produce a socket — a 403, a redirect — raises `WebSocketRejected` carrying the response as `.response`.

The view runs on the test's own thread, inside a copy of the test's context, so the test database transaction is visible to it. Because the connection steps its own event loop, `Client.websocket()` is for synchronous tests, not `async def` ones.

## RequestFactory

[`RequestFactory`](./client.py#RequestFactory) builds `Request` objects without sending them — useful for testing middleware or request handling in isolation. It takes the same keyword arguments as the client methods.

```python
from plain.test import RequestFactory

request = RequestFactory().get("/hello/", query_params={"name": "Alice"})
```

## Test lifecycles

A [`TestLifecycle`](./lifecycle.py#TestLifecycle) is what happens around every test without the test asking: [plain.postgres](../../../plain-postgres/plain/postgres/README.md) wraps each one in a rolled-back transaction, [plain.email](../../../plain-email/plain/email/README.md) resets the outbox. It is for protection — what keeps tests from reaching each other or the outside world — not for setup a test reads, which the test gets in its own body.

There are two places a lifecycle comes from:

- **A package** registers one under the `plain.testing` entry point group. Packages never import the runner.
- **Your project** declares one in `tests/lifecycle.py`.

```python
# tests/lifecycle.py
from contextlib import contextmanager

from plain.test import TestLifecycle, override_settings


class AppTestLifecycle(TestLifecycle):
    @contextmanager
    def around_test(self, test):
        # No test reaches the payment provider, whatever the environment holds.
        with override_settings(PAYMENTS_API_KEY=""):
            yield
```

The file holds exactly one `TestLifecycle` subclass, under any name. Override `around_test` to wrap each test, and `setup_worker` / `teardown_worker` for what happens once per run. See the [plain.testing docs](../../../plain-testing/plain/testing/README.md#project-lifecycle) for the order lifecycles run in.

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
