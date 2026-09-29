# plain.test

**Write and run tests: a client for your app, plain functions with bare asserts, and nothing a test depends on that you can't see in its file.**

- [Overview](#overview)
- [Making requests](#making-requests)
    - [GET requests](#get-requests)
    - [POST requests](#post-requests)
    - [Other HTTP methods](#other-http-methods)
    - [Following redirects](#following-redirects)
    - [Custom headers](#custom-headers)
    - [Schemes and hosts](#schemes-and-hosts)
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
- [Building a request](#building-a-request)
- [Running tests](#running-tests)
    - [Selecting tests](#selecting-tests)
    - [Exit codes](#exit-codes)
    - [Environment](#environment)
- [Where tests live](#where-tests-live)
    - [Shared helpers](#shared-helpers)
- [Reading the output](#reading-the-output)
    - [Failures](#failures)
    - [Large values](#large-values)
    - [What the test wrote](#what-the-test-wrote)
    - [Skipped tests](#skipped-tests)
    - [Collection errors](#collection-errors)
    - [As JSON](#as-json)
- [Assertions](#assertions)
- [What packages do for every test](#what-packages-do-for-every-test)
- [Project lifecycle](#project-lifecycle)
- [Test lifecycles](#test-lifecycles)
- [Testing code outside the app](#testing-code-outside-the-app)
- [How it works](#how-it-works)
- [Design rules](#design-rules)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

A test is a function that makes an assertion. [`Client`](./client.py#Client) makes a request to your app without a server, and gives you back the response that would have been sent.

```python
# tests/test_homepage.py
from plain.test import Client


def test_homepage():
    response = Client().get("/")
    assert response.status_code == 200
```

Run it with `plain test`:

```
$ plain test
Collected 1 test
.

1 passed in 0.04s
```

Everything a test uses is an import, a call, or a `with` block in its own file. The one exception is protection the runner gives every test without being asked, like wrapping it in a database transaction. If you can read the test file, you know what happens.

This page has two halves. The first is how to write a test: the client, `raises`, the decorators, and the `with` helpers, all imported from `plain.test`. The second, from [Running tests](#running-tests) on, is the `plain test` command: how tests are found, what the output means, and what a failed `assert` shows.

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
response = client.request("PROPFIND", "/files/")
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

### Schemes and hosts

A path makes a request to `https://testserver`. When the scheme, host or port is what you're testing, pass a full URL:

```python
response = client.get("http://testserver/")  # a request that didn't come over HTTPS
assert response.redirect_to == "https://testserver/"

response = client.get("https://shop.example.com:8443/cart/")
```

A URL without a port goes to its scheme's port. A followed redirect resolves its `Location` the way a browser does, against the request that was redirected.

## Inspecting responses

Responses are data, not assertion methods — bare `assert` is the assertion API. A [`ClientResponse`](./client.py#ClientResponse) has these names, and no others:

| Name                | What it is                                                                      |
| ------------------- | ------------------------------------------------------------------------------- |
| `status_code`       | The status that went out                                                        |
| `headers`           | The response headers                                                            |
| `cookies`           | The cookies this response set                                                   |
| `body`              | The bytes the response sent                                                     |
| `text`              | The body decoded as a string                                                    |
| `json_data`         | The body parsed as JSON (requires a JSON content type)                          |
| `redirect_to`       | The redirect target on a 3xx response, `None` otherwise                         |
| `redirect_chain`    | The `(url, status_code)` of each redirect that was followed; empty if none were |
| `request`           | The request that produced this response, after middleware ran                   |
| `exception`         | The exception behind a 5xx, when `raise_exceptions=False` kept it a response    |
| `returned_response` | The `Response` object the app returned                                          |

The route that handled the request is `response.request.resolver_match`, which is `None` when a middleware answered it or nothing matched. Whether the body was streamed is `response.returned_response.streaming`.

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

By default, the client re-raises unhandled view exceptions so failures point at the real error. Pass `Client(raise_exceptions=False)` to get the 500 response instead.

### Streaming responses

The client reads a streaming body to the end before it returns, the way a server sends it, so `body` (and `text`, `json_data`) hold what a `StreamingResponse`, `FileResponse`, or `AsyncStreamingResponse` sent:

```python
response = client.get("/export.csv")
assert response.body.startswith(b"id,name")
```

Because the whole body is read, a stream that never ends (an endless event feed) makes the request never return — test those views' pieces directly instead. HEAD requests and bodiless statuses (204, 304) never read the body.

If a body raises partway through, the error is re-raised from the request unless the client was created with `raise_exceptions=False`, in which case `response.exception` holds it and `body` has what came before. A body that fails before producing anything is answered with a 500, as a server would, and `status_code` says so.

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

`patch` takes the object and the attribute name, not a dotted string. On exit the target holds what it held before, which isn't always what reading the attribute finds:

- A class or an instance that only inherited the attribute inherits it again. Nothing is left behind on it.
- A class gets back the `staticmethod` or `classmethod` it held, not the function that reading it returns.
- A property, a slot, a setting on `plain.runtime.settings` and a key of a mapping get back the value they had.

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
        Client(raise_exceptions=False).get("/broken/")

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

A helper makes a `Captured` and calls its `finish(items)` when the block ends. When every capture of a kind reads from one list that grows as things happen, a [`CaptureSource`](./captured.py#CaptureSource) does that for you, and is what makes the captures nest:

```python
from contextlib import contextmanager

from plain.test import Captured, CaptureSource

from .registry import registry

registered = CaptureSource(read=registry.log_entries, clear=registry.clear_log)


@contextmanager
def capture_registrations():
    captured = Captured(helper="capture_registrations")
    with registered.capturing_into(captured):
        yield captured
```

Each capture gets what was added to the list during its own block. The list is emptied when the outermost capture ends, so nothing captured is kept for the rest of the run.

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

It takes `query_params=` and `headers=` like `get()`, plus `subprotocols=` and `timeout=`.

- `ws.send(message)` sends one message to the view; `ws.receive()` returns the next one it sends.
- `ws.close(code=1000, reason="")` closes from the client side and waits for the view to finish. Leaving the `with` block closes it if the test didn't.
- `ws.subprotocol` is the negotiated subprotocol. `ws.request` is the handshake request and `ws.response` is the 101 that answered it, for asserting on its headers and cookies.
- Every call has a timeout (5 seconds by default, `receive(timeout=...)` per call) and raises `TimeoutError` when it elapses.
- An exception raised by the view surfaces from `receive()` and again when the `with` block exits; a view that closes the socket makes `receive()` raise `WebSocketClosed` (from `plain.http`) with its code and reason.
- A handshake that doesn't produce a socket — a 403, a redirect — raises `WebSocketRejected`. Its `.response` is the same kind of response `client.get()` returns. A handshake the app raised from raises that exception, as `client.get()` would, unless the client was created with `raise_exceptions=False`.

The view runs on the test's own thread, inside a copy of the test's context, so the test database transaction is visible to it. Because the connection steps its own event loop, `Client.websocket()` is for synchronous tests, not `async def` ones.

## Building a request

[`build_request()`](./request_builder.py#build_request) builds a `Request` without sending it, for calling a view or a middleware yourself. It takes the method, the path, and the keywords the client's methods take, without `follow_redirects=`.

```python
from plain.test import build_request

request = build_request("GET", "/hello/", query_params={"name": "Alice"})
request = build_request("POST", "/hello/", json_data={"name": "Alice"})
request = build_request("PROPFIND", "/files/")

view = HelloView(request=request)
response = view.get_response()
```

The body is encoded the way the client encodes it, and a path goes to `https://testserver` unless you pass a [full URL](#schemes-and-hosts). The client's cookies and default headers belong to the client, so a built request has only the `headers=` you give it.

It returns an ordinary [`Request`](../../../plain/plain/http/README.md#constructing-a-request). When the body is already bytes and you don't need it encoded, you can construct one directly.

## Running tests

```bash
plain test                                      # everything under the current directory
plain test tests/test_views.py                  # one file
plain test tests/checkout                       # one directory
plain test tests/test_views.py::test_homepage   # one test
plain test -k signup                            # tests whose id contains "signup"
plain test --tag slow                           # only tests tagged "slow"
plain test --exclude-tag slow                   # everything but
plain test -x                                   # stop at the first failure
plain test -v                                   # one line per test, with its duration
plain test --full-values                        # print every value in a failure whole
plain test -s                                   # let what tests print through as they write it
plain test --json                               # one JSON document, when the run is over
```

| Flag                  | What it does                                          |
| --------------------- | ----------------------------------------------------- |
| `-k TEXT`             | Keep the tests whose id contains `TEXT`               |
| `--tag NAME`          | Keep the tests with this tag. Repeat it to allow more |
| `--exclude-tag NAME`  | Drop the tests with this tag. Repeat it to drop more  |
| `-x`, `--fail-fast`   | Stop at the first failure                             |
| `-v`, `--verbose`     | Print one line per test                               |
| `--full-values`       | Print every value and all the output in a failure     |
| `-s`, `--show-output` | Let what tests print and log through as it's written  |
| `--json`              | Print the run as [one JSON document](#as-json)        |
| `--list-passed`       | With `--json`, list the tests that passed too         |

`plain test --help` prints the same list, and the forms a target can take.

Tests run in the same order every time. Within a file, that's the order they're written in.

### Selecting tests

A target is a path, optionally followed by `::` and a name. You can pass several.

| Target                                     | Runs                                 |
| ------------------------------------------ | ------------------------------------ |
| `tests/checkout`                           | Every test file under that directory |
| `tests/test_views.py`                      | Every test in that file              |
| `tests/test_views.py::test_homepage`       | That test, and every case of it      |
| `tests/test_views.py::TestCart`            | Every test in that class             |
| `tests/test_views.py::TestCart::test_add`  | That method                          |
| `'tests/test_email.py::test_valid[empty]'` | That one case                        |

Paths are relative to the directory you run from. Quote a target that names a case, since the shell reads `[` and spaces itself. The [re-run command](#failures) a failure prints is already quoted.

`-k` matches against the whole id, which starts with the file's path. So `-k checkout` keeps every test in `tests/checkout/` as well as any test with "checkout" in its name.

Targets, `-k` and the tag flags combine: a test runs when it's inside a target and passes every filter.

### Exit codes

| Code  | Meaning                                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------- |
| `0`   | Every test that ran passed. Skipped tests don't change this                                             |
| `1`   | A test failed, or a file couldn't be collected                                                          |
| `2`   | The run couldn't start: a target doesn't exist, or the [project lifecycle](#project-lifecycle) is wrong |
| `5`   | No tests matched                                                                                        |
| `130` | The run was stopped with Ctrl-C. What had run by then is reported                                       |

### Environment

`plain test` sets `PLAIN_ENV=test` unless you've set it yourself. It reads no `.env` files of its own. [plain.dev](../../../plain-dev/plain/dev/README.md#env-files) loads them, as it does for every command, and under `PLAIN_ENV=test` that means `.env.test` and `.env`, with `.env.local` left out so personal credentials don't reach the suite. Without plain.dev installed, no `.env` file is loaded.

It also sets `PLAIN_TEST_RUNNING=1`. Plain's own command output reads that to leave out color codes, so a test asserting on the output of a command sees plain text.

## Where tests live

Put tests in `tests/`, beside `app/`. The runner looks for:

- Files named `test_*.py`, in any subdirectory
- Functions named `test_*`
- Classes named `Test*`, and the `test_*` methods on them
- `async def test_*`, which the runner awaits for you

```python
# tests/test_cart.py
from plain.test import Client


def test_empty_cart():
    assert Client().get("/cart/").status_code == 200


class TestCheckout:
    def test_requires_login(self):
        assert Client().get("/checkout/").redirect_to == "/login/"


async def test_price_lookup():
    assert await fetch_price("A-1") == 1200
```

A class is a way to group tests, and nothing more. Each test gets a fresh instance, and there are no setup or teardown methods. A class inherits the tests of its base classes.

An `async def` test uses the client the way any test does. `client.get()` and the rest are ordinary calls, not awaited, whether the view they reach is sync or async, and the test's event loop waits while the request runs. The exception is [`client.websocket()`](#websockets), which is for synchronous tests.

With no target, `plain test` searches the directory you ran it from. It doesn't look in `app/`, in directories whose name starts with a dot, or in `node_modules`.

### Shared helpers

Shared setup is ordinary Python. Write a module and import it:

```python
# tests/helpers.py
from app.users.models import User


def create_user(*, email="test@example.com"):
    return User.query.create(email=email)
```

```python
# tests/accounts/test_profile.py
from helpers import create_user
from plain.test import Client


def test_profile_shows_the_email():
    user = create_user(email="ada@example.com")
    response = Client().get(f"/users/{user.id}/")
    assert "ada@example.com" in response.text
```

`tests/` is on the import path, so `tests/helpers.py` is `helpers`. That's true for a test file in any subdirectory, whichever directory you run from, and whatever target you pass.

It's the only way to import one. `from tests.helpers import ...` and a relative `from .helpers import ...` are [collection errors](#collection-errors) that say what to write instead. A module imported under two names is loaded twice, and the two copies don't share their state.

`tests/` comes first on the import path, so a helper module named like an installed package takes its place. Give a helper module a name nothing else has.

There are no fixtures and no `conftest.py`: a test gets what it needs by calling for it. A `conftest.py` anywhere under the tests is a collection error.

Only files named `test_*.py` have their [assertions](#assertions) rewritten. An `assert` in a helper module fails as a bare `AssertionError`, without the values inside it.

## Reading the output

Each test prints one character as it finishes: `.` passed, `F` failed, `s` skipped. With `-v` each test gets a line of its own:

```
PASSED  tests/test_cart.py::test_empty_cart (0.012s)
SKIPPED tests/test_cart.py::test_refund (Waiting on the new billing API)
```

The last line counts what happened:

```
41 passed, 1 failed, 2 skipped, 1 collection errors in 0.62s
```

That's all a run that passes prints. What a test prints or logs is held while it runs: a test that fails has it printed [with its failure](#what-the-test-wrote), and a test that passes has it thrown away.

### Failures

Every failure is listed after the run. It says where the test failed, what the values inside the assert were, what else the test had in hand, and how to run it again:

```
FAILED tests/test_signup.py::test_signup_redirects

  Traceback (most recent call last):
    File "/project/tests/test_signup.py", line 10, in test_signup_redirects
      assert response.status_code == 302
  AssertionError

  assert response.status_code == 302
    response.status_code = 404
      response = <ClientResponse status_code=404 of <Response status_code=404, "text/plain; charset=utf-8">>

  locals:
    client = <plain.test.client.Client object at 0x10ac756a0>
    email = 'a@example.com'

Re-run: plain test tests/test_signup.py::test_signup_redirects
```

The traceback starts at your test. The runner's own frames are left out.

Under the assert is each part of its expression and what it was, from the outside in: `response.status_code` was `404`, and the `response` it was read from is indented under it. What's written out in the expression (`302`) isn't repeated. See [Assertions](#assertions).

`locals:` is every name the test function had bound when it failed, in the order they were bound, without the ones the assert already printed. It's there for every failure, not only a failed assert, and it's always the test function's own: when the error was raised in something the test called, the traceback shows where and the locals show what the test called it with. A name bound to a module, a class or a function is left out.

The command is quoted wherever a shell would read the id for itself, so you can paste it as it is:

```
Re-run: plain test 'tests/test_price.py::test_total[annual plan]'
```

### Large values

Two values that were expected to be equal, and are too large to read side by side, are printed as what differs between them:

```
  assert profile == expected
    profile = <dict with 7 keys>
    expected = <dict with 6 keys>

  diff:
    --- profile
    +++ expected
    @@ -4,4 +4,3 @@
      'plan': 'annual',
      'renews': '2027-01-01',
    - 'seats': 3,
    - 'trial': False}
    + 'seats': 5}
```

`-` lines are the left side's and `+` lines are the right side's. What is compared depends on what the values are:

| Values                       | Compared by                                                                          |
| ---------------------------- | ------------------------------------------------------------------------------------ |
| Text of more than one line   | Line. By each line's `repr` when they differ in a trailing space or line ending      |
| Two long strings on one line | The first character that differs, with what is around it on each side                |
| Dicts                        | Key, in sorted order                                                                 |
| Lists, tuples and sets       | Item                                                                                 |
| Dataclasses                  | Field                                                                                |
| Anything a package describes | Line of [its description](#test-lifecycles). A model instance is one field to a line |

Values that each fit on a line of 80 characters are printed whole and aren't diffed.

A single value is printed up to 2,000 characters and a diff up to 60 lines. When either is cut short, the last line says by how much:

```
      ... 143,000 more characters (--full-values prints them)
```

Run the test again with `--full-values` to print everything.

A value whose `repr` raises doesn't stop the report. It's printed as `<Order: its repr raised ValueError: no total>`, and everything else is printed as usual.

### What the test wrote

What a failed test wrote to stdout and stderr is printed with its failure, each under its own name and in the order it was written:

```
FAILED tests/test_orders.py::test_order_total

  Traceback (most recent call last):
    File "/project/tests/test_orders.py", line 16, in test_order_total
      assert order["total"] == 42
  AssertionError

  assert order["total"] == 42
    order["total"] = 0
      order = {'total': 0}

  stdout:
    pricing 2 items

  stderr:
    No price for kettle

Re-run: plain test tests/test_orders.py::test_order_total
```

It's held however it was written: `print()`, a log handler, a subprocess the test started, a C extension. What a test reads for itself stays the test's, so `contextlib.redirect_stdout`, `capture_logs`, a `CliRunner` and a subprocess with its own pipes all work as they do anywhere.

A test's output starts when its [lifecycles](#project-lifecycle) enter and ends when they've exited, so what `around_test()` writes on the way in and out belongs to the test. What's written before the first test, while the app is set up and the test database is made, belongs to no test and isn't printed.

The last 10,000 characters of each stream are kept, and the failure says how much came before them. `--full-values` prints all of it:

```
  stdout:
    ... 40,015 characters before this (--full-values prints them)
    line 4000
    line 4001
```

`-s` (`--show-output`) holds nothing: everything is written where it would have been, as it happens, between the progress characters. Use it to watch a test that hangs, or to see what a passing test prints.

A run stopped with Ctrl-C reports what it had: the failures so far, and what the test that was running had written.

```
INTERRUPTED tests/test_sync.py::test_every_page

  stdout:
    fetching page 1
    fetching page 2

Interrupted: 12 passed, 30 not run in 4.18s
```

### Skipped tests

A skipped test is listed with its reason, whether it came from `@skip` or from [`skip_test`](#skipping-from-inside-a-test), and it's counted in the summary:

```
SKIPPED tests/test_uploads.py::test_upload_to_bucket (No bucket reachable from this machine)
```

### Collection errors

A file that can't be turned into tests is a collection error. The other files still run, and the run exits `1`.

```
COLLECTION ERROR tests/test_signup.py

  These tests can't be run as written:

    test_signup(db, client) takes parameters, and nothing passes them in.

  There are no fixtures: nothing is passed to a test by name. A test gets
  what it needs in its body, by calling a helper or entering a `with`
  block, and takes values only from @cases(...).
```

Every test in the file with a problem is named at once. Here is what each message is asking for:

| Message                                                            | What to do                                                                                              |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `test_x(db, client) takes parameters, and nothing passes them in.` | Remove the parameters. Build what the test needs in its body, or pass values with `@cases`              |
| `test_x(a, b) doesn't fit its @cases: case [0] passes 1 value.`    | Make that case pass as many values as the test has parameters                                           |
| `TestCart::test_add() is a method, and has no self parameter.`     | Add `self`                                                                                              |
| `line 8: test_x already has @cases.`                               | Use one `@cases`. For every combination of two lists, write `@cases(*itertools.product(FIRST, SECOND))` |
| `line 8: @skip requires a reason`                                  | Write `@skip("why")`, not a bare `@skip`                                                                |
| `line 8: @tag requires at least one name`                          | Write `@tag("slow")`, not a bare `@tag`                                                                 |
| `from tests.helpers import x should be from helpers import x`      | Write the import the message gives. A [helper module](#shared-helpers) is imported by its bare name     |
| `conftest.py is a pytest file, ...`                                | Move what the file holds, then delete it. See below                                                     |

Each of those is the runner telling you a test is written in a way it can't run, so it prints the message and nothing else. They're all one error, [`TestDefinitionError`](./definition.py#TestDefinitionError).

Anything else is an error of the file's own, raised while it was being imported. It's printed with its traceback, starting at the test file, and with what the file wrote while it was loading:

```
COLLECTION ERROR tests/test_billing.py

  Traceback (most recent call last):
    File "/project/tests/test_billing.py", line 3, in <module>
      from billing_helpers import create_invoice
  ModuleNotFoundError: No module named 'billing_helpers'
```

A `conftest.py` is reported for every directory that has one, with the fixtures it defines listed by name:

```
COLLECTION ERROR tests/conftest.py

  conftest.py is a pytest file, and nothing reads it here. There are no
  fixtures: nothing in this file runs, and nothing is passed to a test
  by name. Move what it holds, then delete the file.

  - A fixture that tests ask for becomes a function in a helper module,
    such as tests/helpers.py. A test imports it
    (`from helpers import create_user`) and calls it in its body. A
    fixture that cleans up after itself becomes a `@contextmanager`
    that the test enters with `with`.
  - A fixture that protected every test without being asked for
    (`autouse=True`) becomes a TestLifecycle's `around_test()`, in
    tests/lifecycle.py.
  - Hooks (`pytest_configure`, `pytest_collection_modifyitems`, ...)
    have no equivalent.

  Fixtures in this file: user, organization

  Autouse fixtures in this file: no_payments
```

The tests that needed nothing from it still run. The ones that asked for a fixture are collection errors of their own.

### As JSON

`plain test --json` prints nothing while the run goes, and one document when it's over. The document is all that's written to stdout, so it can be piped straight to what reads it. It says everything the text report says, with each thing the runner knew as a field of its own: no file, line, id or value has to be read out of a string.

```bash
plain test --json
plain test --json tests/test_orders.py -x
plain test --json --list-passed
```

```json
{
    "version": 1,
    "outcome": "failed",
    "exit_code": 1,
    "duration": 0.0021,
    "command": {
        "argv": [
            "plain",
            "test",
            "--json"
        ],
        "directory": "/project",
        "targets": [],
        "keyword": null,
        "tags": [],
        "exclude_tags": [],
        "fail_fast": false,
        "full_values": false
    },
    "counts": {
        "selected": 3,
        "passed": 1,
        "failed": 1,
        "skipped": 1,
        "not_run": 0,
        "collection_errors": 1
    },
    "tests_listed": "failed_and_skipped",
    "tests": [
        {
            "id": "tests/test_orders.py::test_order_total",
            "file": "tests/test_orders.py",
            "line": 15,
            "name": "test_order_total",
            "tags": [
                "checkout"
            ],
            "outcome": "failed",
            "duration": 0.0014,
            "skip_reason": null,
            "failure": {
                "error_type": "AssertionError",
                "error_message": "",
                "file": "tests/test_orders.py",
                "line": 19,
                "traceback": "Traceback (most recent call last):\n  File \"/project/tests/test_orders.py\", line 19, in test_order_total\n    assert order == {\n    ...<5 lines>...\n    }\nAssertionError\n",
                "frames": [
                    {
                        "file": "tests/test_orders.py",
                        "line": 19,
                        "function": "test_order_total"
                    }
                ],
                "assert": {
                    "expression": "order == {\n    \"items\": [\"tea\", \"kettle\"],\n    \"currency\": \"USD\",\n    \"subtotal\": 40,\n    \"shipping\": 2,\n    \"total\": 42,\n}",
                    "message": null,
                    "parts": [
                        {
                            "source": "order",
                            "depth": 0,
                            "evaluated": true,
                            "value": {
                                "text": "<dict with 5 keys>",
                                "cut_characters": 0
                            }
                        }
                    ],
                    "diff": {
                        "lines": [
                            "--- order",
                            "+++ {'items': ['tea', 'kettle'], 'currency': 'USD', 'subtotal': 40, 'shipping': 2, 'total': 42}",
                            "@@ -1,5 +1,5 @@",
                            " {'currency': 'USD',",
                            "  'items': ['tea', 'kettle'],",
                            "- 'shipping': 0,",
                            "+ 'shipping': 2,",
                            "  'subtotal': 40,",
                            "- 'total': 40}",
                            "+ 'total': 42}"
                        ],
                        "cut_lines": 0
                    }
                },
                "locals": [
                    {
                        "name": "items",
                        "value": {
                            "text": "['tea', 'kettle']",
                            "cut_characters": 0
                        }
                    }
                ],
                "stdout": {
                    "text": "pricing 2 items\n",
                    "cut_characters": 0
                },
                "stderr": {
                    "text": "",
                    "cut_characters": 0
                },
                "rerun_command": "plain test tests/test_orders.py::test_order_total"
            }
        },
        {
            "id": "tests/test_orders.py::test_refund",
            "file": "tests/test_orders.py",
            "line": 28,
            "name": "test_refund",
            "tags": [],
            "outcome": "skipped",
            "duration": 0.0,
            "skip_reason": "Waiting on the new billing API",
            "failure": null
        }
    ],
    "collection_errors": [
        {
            "file": "tests/test_invoices.py",
            "line": 1,
            "is_definition_error": false,
            "error_type": "ModuleNotFoundError",
            "message": "No module named 'billing_helpers'",
            "traceback": "Traceback (most recent call last):\n  File \"/project/tests/test_invoices.py\", line 1, in <module>\n    from billing_helpers import create_invoice\nModuleNotFoundError: No module named 'billing_helpers'",
            "stdout": {
                "text": "",
                "cut_characters": 0
            },
            "stderr": {
                "text": "",
                "cut_characters": 0
            }
        }
    ],
    "stopped": null,
    "interrupted": null,
    "teardown_errors": []
}
```

- **`outcome`** is `"passed"`, `"failed"`, `"interrupted"` or `"stopped"`, and `exit_code` is what the command [exits with](#exit-codes).
- **`tests`** lists the tests that failed and the tests that were skipped. The ones that passed are counted in `counts`. `--list-passed` lists them too, and `tests_listed` says which it was: `"failed_and_skipped"` or `"all"`. A suite of 1,700 passing tests is a document of 5 KB without them and 640 KB with them.
- **Every test has the same fields**, whatever came of it. `skip_reason` and `failure` are `null` when there's nothing to say.
- **A test's `file` and `line`** are where it's defined. **A failure's `file` and `line`** are the statement in the test that failed, or that called what failed. `frames` is the traceback as data, outermost first, down to where the error was raised. A failure that came from a lifecycle, not the test, has `null` for both.
- **`assert`** is `null` for a failure that wasn't a failed assert. Its `parts` are what the text report prints under the assert: each part of the expression as written, how far inside it is, and what it was. A part Python never evaluated has `evaluated: false` and a `null` value.
- **A value is an object**: `text` is what the text report prints, and `cut_characters` is how much the cap left off the end of it. `stdout` and `stderr` are the same, with `cut_characters` counting what was left off the start. `--full-values` leaves nothing off either.
- **`collection_errors`** have `is_definition_error: true` and no traceback when the file is written in a way the runner can't run. `message` says what to write instead.
- **Paths are relative** to `command.directory`, where the command was run from. A path outside it is absolute.
- **`version`** goes up when a field is renamed, removed, or changes what it means. A field being added doesn't change it.

`--json` takes the same targets and filters as any run. It can't be combined with `-v` or `-s`: there's one document, and nothing else goes to stdout.

A run stopped with Ctrl-C still prints its document. `interrupted` says which test was running and what it had written:

```json
{
    "interrupted": {
        "id": "tests/test_sync.py::test_every_page",
        "file": "tests/test_sync.py",
        "line": 1,
        "stdout": {
            "text": "fetching page 1\n",
            "cut_characters": 0
        },
        "stderr": {
            "text": "",
            "cut_characters": 0
        }
    }
}
```

A run that couldn't start prints one too, with no tests in it. `reason` is `"lifecycle_error"`, `"target_not_found"` or `"no_tests_found"`:

```json
{
    "stopped": {
        "reason": "lifecycle_error",
        "message": "/project/tests/lifecycle.py doesn't define a TestLifecycle subclass, so it would protect nothing. Define one:\n\n    from contextlib import contextmanager\n\n    from plain.test import TestLifecycle\n\n\n    class AppTestLifecycle(TestLifecycle):\n        @contextmanager\n        def around_test(self, test):\n            ...\n            yield",
        "traceback": null,
        "stdout": {
            "text": "loading the lifecycle\n",
            "cut_characters": 0
        },
        "stderr": {
            "text": "",
            "cut_characters": 0
        }
    }
}
```

An error in the runner itself is the one thing that isn't a document: it's a traceback on stderr, and the command exits `1`.

`teardown_errors` has an entry for each lifecycle that raised while being taken down, after the last test:

```json
{
    "teardown_errors": [
        {
            "traceback": "Traceback (most recent call last):\n  File \"/project/tests/lifecycle.py\", line 7, in teardown_worker\n    raise RuntimeError(\"still in use\")\nRuntimeError: still in use\n",
            "stdout": {
                "text": "dropping the database\n",
                "cut_characters": 0
            },
            "stderr": {
                "text": "",
                "cut_characters": 0
            }
        }
    ]
}
```

## Assertions

Use bare `assert`. When one fails, the [failure](#failures) shows the expression as you wrote it, and under it every value inside it:

```python
def test_order_total():
    order = create_order(lines=2)
    assert len(order.lines) == expected_lines(order)
```

```
  assert len(order.lines) == expected_lines(order)
    len(order.lines) = 2
      order.lines = [<Line 1>, <Line 2>]
        order = <Order 7>
    expected_lines(order) = 3
```

That's every kind of expression: a comparison, a chain of them, a call, a membership test, `and`, `or`, `not`, arithmetic, `await`. There's nothing to add to an assert to see what went into it.

A message is for saying why, not for printing values. It comes first:

```python
assert items, "the cart should keep what was added before login"
```

```
  the cart should keep what was added before login
  assert items
    items = []
```

### What an assert does to your test

Nothing you can observe. Each part of the expression is evaluated once, in the order Python evaluates it, so an assert that calls something with a side effect behaves the way it would anywhere else. The error raised is an ordinary `AssertionError`, with your message or none.

A part Python never evaluated isn't evaluated by the runner either. The right side of an `and` whose left side was false is reported that way:

```
  assert user.is_admin and user.username == "grace"
    user.is_admin = False
      user = User(id=1, is_admin=False, username='ada')
    user.username == "grace"  (not evaluated)
```

An assert holds on to nothing once it has finished, so a test that checks an object has been freed isn't affected by the assert before it.

Three things are kept whole, without the values inside them: a comprehension, an f-string, and a generator passed to a call (`all(n > 0 for n in rows)` shows what `all()` returned). The values they were built from are in [`locals:`](#failures) when they're the test's own.

Only files named `test_*.py` are rewritten this way. An `assert` in a [helper module](#shared-helpers) fails as a bare `AssertionError`, with the traceback and the test's locals.

For an exception you expect, use [`raises`](#expected-exceptions) from `plain.test`.

## What packages do for every test

An installed Plain package can wrap every test in protection of its own, with no setup on your part. Two do:

- [plain.postgres](../../../plain-postgres/plain/postgres/README.md#testing) creates a test database for the run, and rolls back everything each test wrote.
- [plain.email](../../../plain-email/plain/email/README.md#testing) collects sent mail in memory, so no test sends a real one, and empties the outbox before each test.

A package's protection applies only when the package is in your app's `INSTALLED_PACKAGES`.

Packages ship their test helpers too, in `plain.<package>.test`, and document them in their own READMEs. The Testing section of a package's README is where to look.

## Project lifecycle

Some things have to be true for every test, and a test that forgets one fails in a way that's hard to see: a request reaches a real payment provider, or a rate limiter still holds the last test's count. That's protection, and it doesn't belong in each test's body. Declare it once, in `tests/lifecycle.py`:

```python
# tests/lifecycle.py
from contextlib import contextmanager

from plain.test import TestLifecycle, override_settings

from app.accounts import throttles


class AppTestLifecycle(TestLifecycle):
    @contextmanager
    def around_test(self, test):
        throttles.reset_all()
        # No test reaches the payment provider, whatever the environment holds.
        with override_settings(PAYMENTS_API_KEY=""):
            yield
```

The runner finds the file by its path. There is nothing to register and no other place it looks.

- **One file, one class.** `tests/lifecycle.py` defines exactly one [`TestLifecycle`](#test-lifecycles) subclass, under any name. `around_test(test)` wraps each test, and `setup_worker()` / `teardown_worker()` run once, before the first test and after the last. `describe_value(value)` says how a [failure](#failures) prints a value of your app's.
- **It fails loudly.** If the file is there and doesn't import, defines no `TestLifecycle` subclass, defines more than one, or defines one that can't be created without arguments, the run stops before any test with a message saying which. When the file raised an error of its own, its traceback follows.
- **It runs closest to the test.** Package lifecycles enter first, in the order of their entry point names, and the project's enters last. So the database transaction is already open when yours starts, and yours exits before the transaction is rolled back.
- **It's for protection, not setup.** A user, an organization, a logged-in client: a test that reads one builds it in its body, by calling a helper. If a test would be wrong without the thing but never mentions it, that's the lifecycle's job.

The file has to be `tests/lifecycle.py`. A lifecycle written somewhere the runner doesn't read would protect nothing, so the places one ends up by mistake are checked: `tests/lifecycles.py`, `tests/life_cycle.py`, `tests/lifecycle/__init__.py`, and `lifecycle.py` or `lifecycles.py` beside `tests/`. If one of those is there and mentions `TestLifecycle`, the run stops and says where the file belongs. A `lifecycle.py` deeper inside `tests/` isn't checked, and isn't loaded.

`tests/lifecycle.py` imports [helper modules](#shared-helpers) the way a test file does, by their bare names.

`tests/` is the directory beside `app/`. If you run `plain test` from inside a directory named `tests`, the file is that directory's `lifecycle.py`.

## Test lifecycles

A [`TestLifecycle`](./lifecycle.py#TestLifecycle) is what happens around every test without the test asking. [plain.postgres](../../../plain-postgres/plain/postgres/README.md#testing) wraps each test in a transaction and rolls it back, and [plain.email](../../../plain-email/plain/email/README.md#testing) empties the outbox. It's for protection, which keeps tests from reaching each other or the outside world. It isn't for setup a test reads, which the test gets in its own body.

If you're writing a package, subclass it:

```python
# mypackage/test.py
from contextlib import contextmanager

from plain.test import TestLifecycle

from .registry import Entry, registry


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

    def describe_value(self, value):
        if isinstance(value, Entry):
            return f"Entry(key={value.key!r}, expires={value.expires!r})"
        return None
```

Then register it under the `plain.test` entry point group:

```toml
# pyproject.toml
[project.entry-points."plain.test"]
mypackage = "mypackage.test:MyPackageTestLifecycle"
```

- `setup_worker()` runs once before the first test, and `teardown_worker()` once after the last.
- `around_test(test)` is a context manager entered around each test. `test` is a [`CollectedTest`](./lifecycle.py#CollectedTest), which you can import from `plain.test` to annotate it. `test.id` is the id the runner prints (`tests/test_cart.py::TestCart::test_add[empty]`), `test.name` is the part after the file (`TestCart::test_add[empty]`), and `test.tags` holds its `@tag` names, so a lifecycle can treat a tagged test differently. That's how `@isolated_db` works.
- `describe_value(value)` is what a [failure](#failures) prints for a value your package owns, in place of its `repr`. Return `None` for anything that isn't yours. Use it when the `repr` says too little to fix a test by. The text is printed as it is, and a description of several lines is [diffed](#large-values) by line. It's called for the values in a failed assert and in the test's locals, not for what is inside a list or a dict. It must not change anything the test did, or do anything the test didn't: no queries, no requests.
- `required_package` keeps the lifecycle from loading unless that package is in the app's `INSTALLED_PACKAGES`. An entry point is visible whenever the package is installed in the environment, which is wider than "the app uses it".
- Lifecycles are entered in the order of their entry point names. The runner creates each one with no arguments.

Your package never imports the runner. The entry point is a string, and the runner imports your class when it runs.

A project declares its own lifecycle in `tests/lifecycle.py`, with nothing to register. See [Project lifecycle](#project-lifecycle).

## Testing code outside the app

`plain test` works in a project with no Plain app at all. The runner notices there's no app and leaves the app out:

- Collection, assertion rewriting, targets and the flags all work.
- So does everything in `plain.test` that doesn't need an app: `raises`, `@cases`, `@skip`, `@tag`, `skip_test`, `patch`.
- [`tests/lifecycle.py`](#project-lifecycle) is still loaded.
- Packages' protection is not. There's no test database and no outbox.
- `Client` and `override_settings` need an app, and fail without one.
- `.env.test` is loaded if plain.dev is installed, and not otherwise.

There's nothing to configure. Whether there's an app is decided the way every `plain` command decides it.

One run is one app. In a repository with several apps, run `plain test` once in each.

## How it works

Everything about testing is in this one package, and it's a dev dependency. Nothing in Plain itself imports it.

**`plain.test` is what a test file imports.** `Client`, `build_request`, `raises`, the decorators, the `with` helpers, the `TestLifecycle` class, and the `CollectedTest` a lifecycle is handed.

**`plain.test.runner` is the `plain test` command.** It finds tests, rewrites assertions, runs them and reports. Nothing imports it, your tests included. It imports you. None of its modules is an API, and it knows nothing about the web: a runner that only collects and runs functions is why `plain test` works in a project [with no app](#testing-code-outside-the-app).

**The client is built on Plain's public API.** It constructs a [`Request`](../../../plain/plain/http/README.md#constructing-a-request) and hands it to [`plain.server.inprocess`](../../../plain/plain/server/README.md#handling-requests-in-process), which runs the same middleware, routing and response handling the server does, without a socket. So a test sees what a browser would.

**Each package owns its own testing.** Its helpers are in `plain.<package>.test`, and what it does around every test is a [`TestLifecycle`](#test-lifecycles) it registers under the `plain.test` entry point group:

```toml
# plain-postgres/pyproject.toml
[project.entry-points."plain.test"]
postgres = "plain.postgres.test.lifecycle:PostgresTestLifecycle"
```

An entry point is a string in `pyproject.toml`, so a package declares its lifecycle without depending on this one.

There are two ways to extend the runner, and no others: a package's entry point, and your project's [`tests/lifecycle.py`](#project-lifecycle). There are no plugins and no hooks.

```
your tests         ──import──▶  plain.test  +  plain.<package>.test
plain.test.runner  ──drives──▶  lifecycle entry points  (one per package)
plain.test.runner  ──drives──▶  tests/lifecycle.py      (your project's)
```

## Design rules

`plain.test` is built by eight rules. When a question about the API comes up, these settle it.

1. **No backwards compatibility.** There is one spelling of each thing, and no alias kept for an old one. `/plain-upgrade` rewrites what changes.
2. **Explicit over implicit.** Everything a test depends on is visible in its own file, as an import, a call, or a `with` block. Decorators declare, bodies acquire: a decorator attaches a static fact (its cases, its tags), and runtime state always enters in the body, where its scope is indentation.
3. **One name per thing.** If two spellings do the same job, one goes. The bytes a response sent are `body`, and nothing else.
4. **Fail early, and say what to do.** A mistake is rejected when the file is collected, with a message naming the fix. Nothing is silently overwritten or ignored: a test that asks for parameters nothing passes in, a second `@cases`, a bare `@skip`.
5. **The report tells the truth.** A test that didn't run is reported as skipped, with its reason. Nothing disappears from the count.
6. **Repetition earns a helper, never magic.** When the same lines appear in many tests, the answer is a named function or context manager the tests call. It is never injection.
7. **Standard library first, and helpers live with their owner.** The runner doesn't wrap what Python already does well (`tempfile.TemporaryDirectory`, `math.isclose`, `contextlib.redirect_stdout`). A helper specific to a package ships in that package's `plain.<package>.test`.
8. **Setup is explicit, protection is automatic.** State a test reads is acquired in its body. What guards tests from each other and from the outside world belongs in a lifecycle, which wraps every test without being asked. Packages ship theirs; your project declares its own in [one place](#project-lifecycle).

## FAQs

#### What is the difference between Client and build_request?

`Client` sends the request through the full middleware and view pipeline and returns the response. `build_request()` only constructs the `Request` object — you call the view or middleware yourself.

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

#### How do I debug a failing test?

Put `breakpoint()` where you want to stop and run the test. The debugger gets the terminal: from the breakpoint until that test is over, output is written as it happens. Calling `pdb.set_trace()` yourself doesn't do that, so use `breakpoint()`, or run with `-s`. Every failure prints the command that runs it again, so you can copy that to run the one test.

To see what a test prints without stopping it, `print()` and make it fail, or run it with `-s`.

#### Does coverage work?

Yes. `python -m plain.test` is the same runner as `plain test`, so `coverage run -m plain.test` works with no plugin.

#### Can I use pytest, or pytest plugins?

No. This isn't pytest, and there's nothing to load a plugin into. A library that doesn't depend on pytest keeps working as a library: `freezegun` and `time-machine` for freezing time, `hypothesis` for generated inputs, `unittest.mock` for mocks.

#### What about my editor's test explorer?

Editors speak pytest's protocol, which this runner doesn't. Run tests from the terminal. Every failure prints the command that runs it again. Something that wants a run as data reads [`plain test --json`](#as-json).

#### Why aren't there fixtures?

A fixture hands a test something by the name of its parameter, from a file the test doesn't mention. Here the same needs are met two other ways. Protection every test needs comes from a lifecycle: the database and the outbox from packages, your own from [`tests/lifecycle.py`](#project-lifecycle). Everything else is a function or a context manager the test imports and calls.

#### What replaces an autouse fixture?

It depends on what the fixture was for. If it protected every test (no network, counters reset), it becomes the [project lifecycle](#project-lifecycle). If it set something up for the tests in one file, it becomes a context manager those tests enter with `with`. That repeats a line in each test, and it's the line that says what the test depends on.

#### What replaces `tmp_path`, `capsys` and `approx`?

The standard library. `tempfile.TemporaryDirectory()` for a directory that's removed afterwards, `contextlib.redirect_stdout(io.StringIO())` to read what was printed, and `math.isclose(a, b, abs_tol=...)` inside a bare `assert`.

## Installation

Install the `plain.test` package from [PyPI](https://pypi.org/project/plain.test/) as a dev dependency:

```bash
uv add plain.test --dev
```

Then run your tests:

```bash
plain test
```

There's no configuration file. plain.dev loads `.env.test`, installed packages add their protection, and `tests/lifecycle.py` adds yours.
