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
- [Cookies, logins and sessions](#cookies-logins-and-sessions)
- [Expected exceptions](#expected-exceptions)
- [Test metadata](#test-metadata)
    - [Skipping from inside a test](#skipping-from-inside-a-test)
- [Overriding context](#overriding-context)
- [Capturing what happened](#capturing-what-happened)
    - [Spans](#spans)
    - [Metrics](#metrics)
    - [Log records](#log-records)
    - [Annotating helpers, and writing a capture of your own](#annotating-helpers-and-writing-a-capture-of-your-own)
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

This module is what a test file imports: the client, `raises`, the decorators, and the `with` helpers. Running tests is [plain.testing](../../../plain-testing/plain/testing/README.md), the `plain test` command. That's also where you'll find how tests are discovered, what the output means, and what a failed `assert` shows.

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

The client has a method for `get`, `head`, `options`, `post`, `put`, `patch`, and `delete`. The body-carrying methods take the same arguments as `post`.

```python
response = client.put("/api/users/1/", json_data={"name": "Bob"})
response = client.patch("/api/users/1/", json_data={"name": "Bob"})
response = client.delete("/api/users/1/")
```

For any other method, `request()` takes the method by name and the same keywords:

```python
response = client.request(method="PROPFIND", path="/files/")
assert response.status_code == 405
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

Responses are data, not assertion methods — bare `assert` is the assertion API. A [`ClientResponse`](./client.py#ClientResponse) has these names, and no others:

| Name                | What it is                                                                          |
| ------------------- | ----------------------------------------------------------------------------------- |
| `status_code`       | The status that went out                                                            |
| `headers`           | The response headers                                                                |
| `cookies`           | The cookies this response set                                                       |
| `body`              | The bytes the response sent                                                         |
| `text`              | The body decoded as a string                                                        |
| `json_data`         | The body parsed as JSON (requires a JSON content type)                              |
| `redirect_to`       | The redirect target on a 3xx response, `None` otherwise                             |
| `redirect_chain`    | The `(url, status_code)` of each redirect that was followed; empty if none were     |
| `request`           | The request that produced this response, after middleware ran                       |
| `exception`         | The exception behind a 5xx, when `raise_request_exception=False` kept it a response |
| `streaming`         | Whether the body was streamed                                                       |
| `resolver_match`    | The URL route the path resolves to, `None` if it has none                           |
| `returned_response` | The `Response` object the app returned                                              |

```python
response = client.get("/api/users/")
assert response.json_data["users"][0]["name"] == "Alice"
```

Everything but the last describes what was sent. `returned_response` is the object itself, for an assertion about its type or about an attribute only that type has:

```python
from plain.http import FileResponse

response = client.get("/report.pdf")
assert isinstance(response.returned_response, FileResponse)
```

Its own `content` and `status_code` can differ from what went out — after a HEAD, a 204, or a streaming body that failed — which is why the client's response doesn't pass them through. Reading any other name raises an `AttributeError` that lists the ones above.

By default, the client re-raises unhandled view exceptions so failures point at the real error. Pass `Client(raise_request_exception=False)` to get the 500 response instead.

### Streaming responses

The client reads a streaming body to the end before it returns, the way a server sends it, so `body` (and `text`, `json_data`) hold what a `StreamingResponse`, `FileResponse`, or `AsyncStreamingResponse` sent:

```python
response = client.get("/export.csv")
assert response.body.startswith(b"id,name")
```

Because the whole body is read, a stream that never ends (an endless event feed) makes the request never return — test those views' pieces directly instead. HEAD requests and bodiless statuses (204, 304) never read the body.

If a body raises partway through, the error is re-raised from the request unless the client was created with `raise_request_exception=False`, in which case `response.exception` holds it and `body` has what came before. A body that fails before producing anything is answered with a 500, as a server would, and `status_code` says so.

## Cookies, logins and sessions

A client keeps the cookies its responses set and sends them with every request after, so a flow that logs in through a form stays logged in. `client.cookies` is that jar, a `SimpleCookie`:

```python
client.cookies["theme"] = "dark"
response = client.get("/")  # sent with Cookie: theme=dark

client.cookies.clear()
```

Logging in and reading the session are built on it, and ship with the packages that own them:

- [plain.auth](../../../plain-auth/plain/auth/README.md#testing-with-authenticated-users): `login_client(client, user)` and `logout_client(client)`
- [plain.sessions](../../../plain-sessions/plain/sessions/README.md#testing): `get_client_session(client)`

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

## Capturing what happened

`capture_spans`, `capture_metrics` and `capture_logs` each record one kind of thing while a block runs, and all three hand back the same shape: a read-only sequence of what was captured, in the order it happened.

```python
from plain.test import Client, capture_logs, capture_spans


def test_homepage():
    with capture_spans() as spans, capture_logs() as logs:
        Client().get("/")

    assert "GET /" in [span.name for span in spans]
    assert logs == []
```

It's a sequence, so `len()`, indexing, slicing, iteration, `in` and truthiness work, and there's no method to call to get at the items. It compares equal to a list or tuple holding the same items, so `assert logs == []` means what it says.

**Read a capture after its block.** A capture is complete when the block ends: that's when a span that was still open has ended, and when metrics are collected. Reading it inside the block raises, so a test can't pass or fail on part of what happened:

```
RuntimeError: capture_spans() is still capturing — read what it captured after the `with capture_spans()` block ends, not inside it.
```

A block that raises still finishes its capture, so what was captured up to that point is there to read. Captures can be nested, and one opened inside another doesn't take anything from the outer one.

### Spans

```python
from opentelemetry.trace import SpanKind

from plain.test import capture_spans


def test_homepage_span():
    with capture_spans() as spans:
        Client().get("/")

    [server_span] = spans.filter(kind=SpanKind.SERVER)
    assert server_span.attributes is not None
    assert server_span.attributes["http.route"] == "/"
```

[`capture_spans`](./otel.py#capture_spans) captures the spans that end during the block. Each is OpenTelemetry's own `ReadableSpan`, so `name`, `kind`, `attributes`, `status`, `events`, `parent` and `context` are all there.

`spans.filter(name=..., kind=...)` returns the spans with that name, of that kind, or both, as a list. Unpack it when there should be exactly one (`[span] = spans.filter(name="claim job")`), or index it when there may be several.

### Metrics

```python
from plain.test import capture_metrics


def test_request_duration_is_recorded():
    with capture_metrics() as metrics:
        Client().get("/")

    [point] = metrics.histogram_points(
        "http.server.request.duration",
        attributes={"http.route": "/"},
    )
    assert point.count == 1
```

[`capture_metrics`](./otel.py#capture_metrics) captures the metrics recorded during the block. Each item is OpenTelemetry's own `Metric`, but what a test usually wants are a metric's data points, and those come in two kinds:

- `metrics.number_points(name)`: the points of a counter, an up-down counter or a gauge. Each has a `value`.
- `metrics.histogram_points(name)`: the points of a histogram. Each has a `count`, a `sum`, a `min` and a `max`.

Both take `attributes={...}` to keep only the points that carry all of those attributes, and both return an empty list for a metric nothing was recorded for. Asking for the wrong kind raises and names the right one.

Metrics are collected when the block ends, and that's also when an observable instrument is asked for its value. If a gauge reports the size of a pool, the pool has to still be there, so open the capture inside the block that keeps it alive:

```python
def test_pool_reports_its_connections():
    connection = pool.acquire()
    try:
        with capture_metrics() as metrics:
            pass
    finally:
        pool.release(connection)

    assert metrics.number_points("db.client.connection.count")
```

### Log records

```python
from plain.test import Client, capture_logs


def test_server_error_is_logged():
    with capture_logs() as logs:
        Client(raise_request_exception=False).get("/broken/")

    assert "Server error" in logs.messages
    assert logs[0].path == "/broken/"
```

[`capture_logs`](./logs.py#capture_logs) captures the records logged during the block. Each is a `logging.LogRecord`, and `logs.messages` is the formatted message of every one. Structured context passed as `context={...}` lands on the record as ordinary attributes, so `logs[0].path` reads it back.

With no arguments it captures the whole `plain` and `app` trees; name loggers to narrow it (`capture_logs("plain.jobs")`). Plain's loggers don't propagate to the root logger, so attaching a handler there would see nothing. This attaches to the named loggers directly, lowers their level for the block, and restores everything on exit.

`logs.span_context_for(message)` returns the OpenTelemetry span context that was current when that record was logged. That's the check behind "this exception log landed _inside_ its error span": a record logged with no span current exports with empty trace and span ids, and the one failure gets reported twice downstream (the span's exception event plus an orphaned error log).

```python
from plain.test import capture_logs, capture_spans


def test_claim_failure_log_is_correlated():
    with capture_spans() as spans, capture_logs("plain.jobs") as logs:
        run_the_failing_claim()

    [span] = spans.filter(name="claim job")
    assert span.context is not None
    assert logs.span_context_for("Failed to claim job").trace_id == (
        span.context.trace_id
    )
```

### Annotating helpers, and writing a capture of your own

What the three yield is importable for annotating your own helpers: `CapturedSpans`, `CapturedMetrics` and `CapturedLogs`.

```python
from opentelemetry.trace import SpanKind

from plain.test import CapturedSpans


def route_of(spans: CapturedSpans) -> str:
    [server_span] = spans.filter(kind=SpanKind.SERVER)
    assert server_span.attributes is not None
    return str(server_span.attributes["http.route"])
```

All three are a [`Captured`](./captured.py#Captured), and a package that ships its own capture helper builds on the same class so it reads the same way. [`capture_queries`](../../../plain-postgres/plain/postgres/README.md#testing) in `plain.postgres.test` is one.

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
- `ws.subprotocol` is the negotiated subprotocol. `ws.request` is the handshake request and `ws.response` is the 101 that answered it, for asserting on its headers and cookies.
- Every call has a timeout (5 seconds by default, `receive(timeout=...)` per call) and raises `TimeoutError` when it elapses.
- An exception raised by the view surfaces from `receive()` and again when the `with` block exits; a view that closes the socket makes `receive()` raise `WebSocketClosed` (from `plain.http`) with its code and reason.
- A handshake that doesn't produce a socket — a 403, a redirect — raises `WebSocketRejected`. Its `.response` is the same kind of response `client.get()` returns.

The view runs on the test's own thread, inside a copy of the test's context, so the test database transaction is visible to it. Because the connection steps its own event loop, `Client.websocket()` is for synchronous tests, not `async def` ones.

## RequestFactory

[`RequestFactory`](./client.py#RequestFactory) builds `Request` objects without sending them — useful for testing middleware or request handling in isolation. It has the same methods as the client and takes the same keywords, without `follow_redirects=`.

```python
from plain.test import RequestFactory

request = RequestFactory().get("/hello/", query_params={"name": "Alice"})
request = RequestFactory().post("/hello/", json_data={"name": "Alice"})
request = RequestFactory().request(method="PROPFIND", path="/files/")
```

Requests are HTTPS to `testserver` unless you say otherwise: `secure=False` makes one plain HTTP, and `headers={"Host": "example.com"}` names another host.

## Test lifecycles

A [`TestLifecycle`](./lifecycle.py#TestLifecycle) is what happens around every test without the test asking. [plain.postgres](../../../plain-postgres/plain/postgres/README.md#testing) wraps each test in a transaction and rolls it back, and [plain.email](../../../plain-email/plain/email/README.md#testing) empties the outbox. It's for protection, which keeps tests from reaching each other or the outside world. It isn't for setup a test reads, which the test gets in its own body.

If you're writing a package, subclass it:

```python
# mypackage/test.py
from contextlib import contextmanager

from plain.test import TestLifecycle

from .registry import registry


class MyPackageTestLifecycle(TestLifecycle):
    required_package = "mypackage"

    def setup_worker(self):
        registry.use_in_memory_store()

    def teardown_worker(self):
        registry.use_default_store()

    @contextmanager
    def around_test(self, test):
        registry.clear()
        yield
```

Then register it under the `plain.testing` entry point group:

```toml
# pyproject.toml
[project.entry-points."plain.testing"]
mypackage = "mypackage.test:MyPackageTestLifecycle"
```

- `setup_worker()` runs once before the first test, and `teardown_worker()` once after the last.
- `around_test(test)` is a context manager entered around each test. `test` is a [`CollectedTest`](./lifecycle.py#CollectedTest), which you can import from `plain.test` to annotate it. `test.id` is the id the runner prints (`tests/test_cart.py::TestCart::test_add[empty]`), `test.name` is the part after the file (`TestCart::test_add[empty]`), and `test.tags` holds its `@tag` names, so a lifecycle can treat a tagged test differently. That's how `@isolated_db` works.
- `required_package` keeps the lifecycle from loading unless that package is in the app's `INSTALLED_PACKAGES`. An entry point is visible whenever the package is installed in the environment, which is wider than "the app uses it".
- Lifecycles are entered in the order of their entry point names. The runner creates each one with no arguments.

Your package never imports the runner. The entry point is a string, and the runner imports your class when it runs.

A project declares its own lifecycle in `tests/lifecycle.py`, with nothing to register. See [Project lifecycle](../../../plain-testing/plain/testing/README.md#project-lifecycle).

## FAQs

#### What is the difference between Client and RequestFactory?

`Client` sends the request through the full middleware and view pipeline and returns the response. `RequestFactory` only constructs the `Request` object — you call the view or middleware yourself.

#### How do I test file uploads?

Pass file-like objects via `files={...}` — they're encoded into a multipart body together with `form_data`.

#### Where are the database and email helpers?

With their packages. `plain.test` holds only what isn't specific to one package, and each package documents its own helpers:

- [plain.postgres](../../../plain-postgres/plain/postgres/README.md#testing): `isolated_db`, `capture_queries`, `max_queries`
- [plain.email](../../../plain-email/plain/email/README.md#testing): `outbox`
- [plain.auth](../../../plain-auth/plain/auth/README.md#testing-with-authenticated-users): `login_client`, `logout_client`
- [plain.sessions](../../../plain-sessions/plain/sessions/README.md#testing): `get_client_session`

#### How do I get a temporary directory, or read what was printed?

From the standard library. `tempfile.TemporaryDirectory()` gives a directory that's removed when the block exits, and `contextlib.redirect_stdout(io.StringIO())` collects what was printed.

## Installation

`plain.test` ships with Plain — no installation needed. To run tests, add the [plain.testing](../../../plain-testing/plain/testing/README.md) dev dependency:

```bash
uv add plain.testing --dev
```
