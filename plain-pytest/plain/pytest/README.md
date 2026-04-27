# plain.pytest

**Run tests with pytest and useful fixtures for Plain applications.**

- [Overview](#overview)
- [Fixtures](#fixtures)
    - [`settings`](#settings)
    - [`testbrowser`](#testbrowser)
    - [`otel_spans`](#otel_spans)
    - [`otel_metrics`](#otel_metrics)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can run tests using the `plain test` command, which wraps pytest and automatically loads environment variables from `.env.test` if it exists.

```bash
plain test
```

Any additional arguments are passed directly to pytest.

```bash
plain test -v --tb=short
plain test tests/test_views.py
```

A basic test looks like this:

```python
from plain.test import Client


def test_homepage():
    client = Client()
    response = client.get("/")
    assert response.status_code == 200
```

The [`Client`](/plain/plain/test/client.py#Client) class comes from [`plain.test`](/plain/plain/test/README.md) and lets you make requests to your app without starting a server.

## Fixtures

### `settings`

The [`settings`](./plugin.py#settings) fixture provides access to your Plain settings during tests. Any modifications you make are automatically restored when the test completes.

```python
def test_debug_mode(settings):
    settings.DEBUG = True
    assert settings.DEBUG is True
    # After this test, DEBUG is restored to its original value
```

### `testbrowser`

The [`testbrowser`](./plugin.py#testbrowser) fixture gives you a [`TestBrowser`](./browser.py#TestBrowser) instance that wraps [Playwright](https://playwright.dev/python/) and runs a real Plain server in the background. This is useful for end-to-end browser testing.

```python
def test_login_page(testbrowser):
    page = testbrowser.new_page()
    page.goto("/login/")
    assert page.title() == "Login"
```

The browser connects to a test server running over HTTPS on a random available port. Self-signed certificates are generated automatically.

**Authentication helpers**

You can log in a user without going through the login form using [`force_login`](./browser.py#force_login).

```python
def test_dashboard(testbrowser, user):
    testbrowser.force_login(user)
    page = testbrowser.new_page()
    page.goto("/dashboard/")
    assert "Welcome" in page.content()
```

To log out, use [`logout`](./browser.py#logout), which clears all cookies.

```python
def test_logout_clears_session(testbrowser, user):
    testbrowser.force_login(user)
    testbrowser.logout()
    page = testbrowser.new_page()
    page.goto("/dashboard/")
    assert "Login" in page.content()
```

**URL discovery**

The [`discover_urls`](./browser.py#discover_urls) method crawls your site starting from given URLs and returns all discovered internal links. This is useful for smoke testing.

```python
def test_no_broken_links(testbrowser, user):
    testbrowser.force_login(user)
    urls = testbrowser.discover_urls(["/"])
    assert len(urls) > 0
```

**Database isolation**

If `plain.postgres` is installed, the `testbrowser` fixture automatically uses the [`isolated_db`](/plain-postgres/plain/postgres/test/pytest.py#isolated_db) fixture and passes the database connection to the test server. This means your browser tests and your test code share the same database state.

### `otel_spans`

The [`otel_spans`](./plugin.py#otel_spans) fixture gives you the OpenTelemetry spans emitted during the test. It returns an [`InMemorySpanExporter`](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.export.html#opentelemetry.sdk.trace.export.in_memory_span_exporter.InMemorySpanExporter) — call `.get_finished_spans()` to read them.

```python
from opentelemetry import trace


def test_homepage_span(otel_spans):
    Client().get("/")

    spans = otel_spans.get_finished_spans()
    server_span = next(s for s in spans if s.kind == trace.SpanKind.SERVER)
    assert server_span.name == "GET /"
    assert server_span.attributes["http.route"] == "/"
    assert server_span.attributes["http.response.status_code"] == 200
```

The fixture clears previously captured spans on entry, so each test sees only its own.

### `otel_metrics`

The [`otel_metrics`](./plugin.py#otel_metrics) fixture gives you the OpenTelemetry metrics emitted during the test. It returns an [`InMemoryMetricReader`](https://opentelemetry-python.readthedocs.io/en/latest/sdk/metrics.export.html#opentelemetry.sdk.metrics.export.InMemoryMetricReader) — call `.get_metrics_data()` to read accumulated points, or `.collect()` to force collection of observable instruments.

```python
def test_request_duration_metric(otel_metrics):
    Client().get("/")

    data = otel_metrics.get_metrics_data()
    metric_names = {
        m.name
        for rm in data.resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
    }
    assert "http.server.request.duration" in metric_names
```

The fixture drains any prior observations on entry. Both fixtures share the same global tracer/meter providers — fine to use them together in one test.

## FAQs

#### Do I need Playwright installed?

The `testbrowser` fixture requires `playwright` and `pytest-playwright` to be installed, but they are not dependencies of this package. If you only use the `settings` fixture, you don't need Playwright.

```bash
uv add playwright pytest-playwright --dev
playwright install
```

#### How do I use a `.env.test` file?

Create a `.env.test` file in your project root with test-specific environment variables. The `plain test` command automatically loads it before running pytest.

```bash
# .env.test
DATABASE_URL=postgres://localhost/myapp_test
SECRET_KEY=test-secret-key
```

#### How do I run a specific test?

Pass the test path and any pytest options after `plain test`.

```bash
plain test tests/test_views.py::test_homepage -v
```

## Installation

Install the `plain.pytest` package from [PyPI](https://pypi.org/project/plain.pytest/):

```bash
uv add plain.pytest --dev
```

The `settings` and `testbrowser` fixtures are automatically available in all tests — no `conftest.py` import needed.

If you're using the `testbrowser` fixture, also install Playwright:

```bash
uv add playwright pytest-playwright --dev
playwright install chromium
```
