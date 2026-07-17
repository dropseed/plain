# plain.testing

**Plain's own test runner — plain functions, bare asserts, and a runner that knows your whole stack.**

- [Overview](#overview)
- [Writing tests](#writing-tests)
- [Assertions](#assertions)
- [Test metadata](#test-metadata)
- [Overriding context](#overriding-context)
- [Database access](#database-access)
- [Package test helpers](#package-test-helpers)
- [Running tests](#running-tests)
- [Testing code outside the app](#testing-code-outside-the-app)
- [Parallelism](#parallelism)
- [Flake detection](#flake-detection)
- [Performance assertions](#performance-assertions)
- [Route coverage](#route-coverage)
- [Output for agents](#output-for-agents)
- [Browser testing](#browser-testing)
- [Built-in tests](#built-in-tests)
- [How it works](#how-it-works)
- [Migrating from pytest](#migrating-from-pytest)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

A test is a function that makes an assertion.

```python
from plain.test import Client


def test_homepage():
    response = Client().get("/")
    assert response.status_code == 200
```

Run it with `plain test`:

```bash
plain test
```

Everything a test uses is either an explicit import, an explicit `with` block, or something the framework does for every test automatically (like wrapping it in a database transaction). If you can read the test file, you know everything that happens.

And because the runner is part of the framework, it knows your whole stack: every test runs inside OpenTelemetry capture, so failures report the queries and spans behind them; the runner knows your URL routes, so it can tell you which ones are untested; and the database, email outbox, and cache are isolated per test without any setup on your part.

The guiding rule for the API: **decorators declare, bodies acquire.** Decorators attach static facts to a test (its cases, its tags, its timeout). Runtime state — settings overrides, frozen time, captured spans — always enters through a `with` block or a function call in the body, where you can see its scope.

## Writing tests

Tests live in `tests/` and follow the conventions you already know:

- Files named `test_*.py` (searched recursively)
- Functions named `test_*`
- `async def test_*` works natively, with the same executor semantics as the production server.

```python
# tests/test_signup.py
from plain.test import Client

from app.users.models import User


def test_signup_creates_user():
    response = Client().post("/signup/", data={"email": "a@example.com"})
    assert response.status_code == 302
    assert User.query.count() == 1
```

Shared setup is ordinary Python — write a helper module and import it:

```python
# tests/helpers.py
from app.users.models import User


def create_user(*, email="test@example.com"):
    return User.test.create(email=email)
```

```python
# tests/test_dashboard.py
from plain.test import Client

from .helpers import create_user


def test_dashboard_requires_login():
    user = create_user()
    client = Client()
    client.force_login(user)
    assert client.get("/dashboard/").status_code == 200
```

If a test needs something, it imports it or builds it — everything in a test file traces back to a name you can see.

## Assertions

Use bare `assert`. Failures show the values involved, with diffs for the common shapes (`==`, `in`, `is`, comparisons, truthiness):

```
FAILED tests/test_signup.py::test_signup_creates_user

    assert response.status_code == 302
           |        |
           |        200
           <Response 200 text/html>

Re-run: plain test tests/test_signup.py::test_signup_creates_user
```

For expected exceptions, use `raises`:

```python
from plain.test import raises


def test_invalid_email():
    with raises(ValidationError):
        validate_email("nope")
```

`raises` also exposes the caught exception for further assertions:

```python
with raises(ValidationError) as caught:
    validate_email("nope")
assert "email" in str(caught.exception)
```

## Test metadata

Decorators declare static facts about a test. There are four:

```python
from plain.test import cases, skip, tag, timeout


@cases(
    ("a@example.com", True),
    ("nope", False),
    ("@missing-local.com", False),
)
def test_email_validation(email, valid):
    assert is_valid_email(email) is valid


@skip("Waiting on the new billing API")
def test_invoice_totals(): ...


@tag("slow")
@timeout(30)
def test_big_import(): ...
```

- `@cases(...)` — parametrization. Each tuple becomes its own test, reported as `test_email_validation[0]`, `test_email_validation[1]`, etc., with the case values shown in the report.
- `@skip(reason)` — always skipped, reason shown in the report.
- `@tag(name)` — labels for selection: `plain test --tag slow` or `plain test --exclude-tag slow`.
- `@timeout(seconds)` — per-test override of the runner's default timeout.

That's the whole decorator surface — anything dynamic belongs in the test body.

## Overriding context

Runtime state changes are context managers, so their scope is visible as indentation:

```python
from plain.test import override_settings, freeze_time, patch


def test_debug_error_page():
    with override_settings(DEBUG=True):
        response = Client().get("/broken/")
    assert b"Traceback" in response.content


def test_code_expiry():
    with freeze_time("2026-01-01T00:00:00Z"):
        code = generate_login_code(user)
    with freeze_time("2026-01-02T00:00:00Z"):
        assert code_is_expired(code)


def test_external_call():
    with patch(billing, "charge_card", lambda **kwargs: "ch_123"):
        checkout(cart)
```

- `override_settings(**settings)` — set any Plain settings for the block; originals restored on exit.
- `freeze_time(when)` — freeze `datetime.now()` and friends. Sessions, login codes, job scheduling, and cache expiry are all time-dependent, so this ships in the box.
- `patch(target, name, value)` — replace an attribute for the block; restored on exit.

Composition is nesting:

```python
with override_settings(DEBUG=True), freeze_time("2026-01-01"):
    ...
```

## Database access

If `plain.postgres` is installed, every test gets an isolated database automatically. There is nothing to declare:

- A test database is created once per run — migrated and converged — and kept as a **template**.
- Each worker process gets its own fast clone of the template (`CREATE DATABASE ... TEMPLATE ...`).
- Each test runs inside a transaction that is rolled back afterward.

The transaction is opened lazily, on the first database connection checkout — so tests that never touch the database pay nothing, and tests that do are isolated automatically. The runner owns the connection, so it always knows which kind of test it's running.

Tests that need a real, separately-connectable database (a live server in a browser test, connection behavior itself) get a dedicated database instead of a rolled-back transaction — see [Browser testing](#browser-testing).

## Package test helpers

Installed Plain packages expose their test helpers under `plain.<package>.test`:

```python
from plain.email.test import outbox
from plain.jobs.test import capture_jobs
from plain.flags.test import override_flag
from plain.test import capture_spans, capture_metrics


def test_signup_sends_welcome_email():
    with capture_jobs() as jobs:
        Client().post("/signup/", data={"email": "a@example.com"})
        jobs.run_all()  # process enqueued jobs in-process, same transaction

    assert len(outbox) == 1
    assert outbox[0].to == ["a@example.com"]


def test_homepage_traced():
    with capture_spans() as spans:
        Client().get("/")
    server_span = spans.find(kind="SERVER")
    assert server_span.attributes["http.route"] == "/"
```

- `outbox` — every email sent during the test; reset automatically between tests.
- `capture_jobs()` — jobs enqueue as real rows; assert on what's pending, then `jobs.run_all()` (or filter by job class or queue) to execute them synchronously through the real job-loading path.
- `override_flag(name, value)` — pin a feature flag for the block.
- `capture_spans()` / `capture_metrics()` — the OpenTelemetry signals emitted during the block, with accessors like `spans.find(kind=..., name=...)`.

The cache is isolated per test automatically, like the database — no helper needed.

## Running tests

```bash
plain test                              # everything
plain test tests/test_views.py          # one file
plain test tests/test_views.py::test_homepage
plain test -k signup                    # filter by name substring
plain test --tag slow                   # only tagged tests
plain test --exclude-tag slow           # everything but
plain test -x                           # stop on first failure
plain test --lf                         # re-run last failures
plain test --pdb                        # debugger on failure
plain test -v                           # verbose
```

`plain test` loads `.env.test` (via the standard env precedence ladder) and runs Plain's `setup()` before collecting — no configuration needed.

Test order is **deterministic by default**: same code, same order, every time. Failure state for `--lf` is stashed in the gitignored `.plain/` directory.

## Testing code outside the app

Not everything in your repo is the app. A common shape is a uv workspace with supporting packages alongside it:

```
pyproject.toml        # workspace root — the Plain app lives here
app/
tests/
packages/
  billing/            # a plain Python package, no Plain dependency
    pyproject.toml
    src/billing/
    tests/
```

There are two situations, and both work:

**Alongside an app.** `plain test packages/billing/tests` runs those tests under the app's runtime like any others. Pure-Python tests don't notice — the database lifecycle is lazy, so tests that never touch Plain pay nothing for it.

**No app at all.** In a project with no Plain app, the runner switches to **library mode** instead of erroring. Collection, assertion rewriting, `raises`, `@cases` and the other decorators, `patch`, `freeze_time`, parallelism, shuffling, and `--json` all work — none of them need a running app. Helpers that do need one (`Client`, `override_settings`, the database lifecycle) raise a clear error saying so. This makes `plain test` a usable test runner for any Python package, not just Plain apps.

The runner resolves the app the same way every `plain` command does; the presence or absence of an app picks the mode — there's nothing to configure.

One invocation is one runtime context. In a monorepo where each package has its own test app (the plain framework repo itself is ~30 packages shaped exactly like this), you run the runner once per package — which is also a natural outer parallelism boundary.

## Parallelism

Parallel execution is built into the runner:

```bash
plain test -n auto     # one worker per CPU
plain test -n 4
```

Each worker is a separate process with its own clone of the template database — workers never share state, and the expensive migrate-and-converge setup happens exactly once regardless of worker count.

To hunt order-dependent tests, shuffle with a seed:

```bash
plain test --shuffle           # random seed, printed in the report
plain test --shuffle 1234      # reproduce a specific order
```

Every failure report includes the seed, so any ordering-related failure is reproducible from the output alone.

## Flake detection

When a test fails, the runner automatically re-runs it once and **classifies** the result instead of hiding it:

- Fails again → a real failure, reported normally.
- Passes on re-run → reported as **flaky — and still a failure.**

```
FLAKY tests/test_webhooks.py::test_delivery_retry
    Failed on first run, passed on re-run (same order, same seed).
    Flaky tests are failures. Re-run: plain test tests/test_webhooks.py::test_delivery_retry --shuffle 8471
```

A flake is a bug report about the test, not noise to suppress. Disable re-running entirely with `--no-rerun` (useful when a failure is expected and you want the fastest loop).

## Performance assertions

Every test runs inside OpenTelemetry capture, which makes the framework's performance opinions assertable:

```python
from plain.test import max_queries


def test_dashboard_query_budget(user):
    client = Client()
    client.force_login(user)
    with max_queries(5):
        client.get("/dashboard/")
```

- `max_queries(n)` — the block fails if more than `n` database queries execute. A query budget is a contract, checked on every run.
- **N+1 detection** — failure reports flag repeated query shapes automatically, the same analysis as `plain request --json`.
- **Strict mode** — `plain test --strict` turns framework opinions into failures: any query executed during a template render fails the test ("fetch all data in the view" stops being advice and becomes a check).

## Route coverage

The runner knows every URL pattern registered with your `Router`, and every request made through `Client` or the browser records the route it hit. Put together:

```bash
plain test --route-coverage
```

```
Route coverage: 34/40 routes exercised

Never exercised:
  /billing/invoices/<id>/pdf/
  /settings/api-keys/
  ...
```

Route-level coverage answers the question line coverage can't: is this endpoint tested at all? It's reported per route, with no instrumentation overhead — the data is already in the spans.

## Output for agents

Test output is designed to be acted on — by you or by an agent — without follow-up questions.

Every failure ends with a self-contained block: the assertion diff, the query/span summary, and the exact re-run command including the seed.

For structured output:

```bash
plain test --json
```

Emits one JSON document: per-test status (passed / failed / flaky / skipped), assertion diffs as data, durations, query counts, and N+1 flags. No parsing terminal noise.

For fast iteration on a diff:

```bash
plain test --changed
```

Runs only the tests affected by your uncommitted changes, using the test→file coverage map recorded on previous runs. "Run the 9 relevant tests in 2 seconds" instead of the whole suite.

## Browser testing

End-to-end tests drive a real browser against a real server:

```python
from plain.testing.browser import testbrowser


def test_dashboard(user):
    with testbrowser() as browser:
        browser.force_login(user)
        page = browser.new_page()
        page.goto("/dashboard/")
        assert "Welcome" in page.content()
```

`testbrowser()` boots a Plain server over HTTPS on a random port (self-signed certs generated automatically) and launches Playwright against it. Because the server is a separate process, the test gets a dedicated database instead of a rolled-back transaction — the browser and your test code see the same data.

Helpers: `force_login(user)` / `logout()` skip the login form; `discover_urls(["/"])` crawls internal links for smoke testing.

Playwright is not a dependency of this package — install it when you use browser tests:

```bash
uv add playwright --dev
playwright install chromium
```

## Built-in tests

The framework knows enough about your app to test parts of it before you've written anything. `plain test` includes a built-in suite alongside your own tests:

- **Routes respond** — every registered route returns something other than a 500 for an anonymous user and a logged-in user (auth redirects and 403s count as passing).
- **Admin renders** — every admin view renders for a staff user.
- **Preflight passes** — run once at suite start, so misconfiguration fails fast as one clear error instead of forty confusing ones.

Built-in results appear as normal tests (`builtin/routes::orders_detail`), so `-k`, `--json`, and failure output all apply. Skip them with `--no-builtin`, or exclude specific routes that require external state:

```python
# app/settings.py
TEST_BUILTIN_EXCLUDE_ROUTES = [
    "/webhooks/stripe/",
]
```

A brand-new Plain project has meaningful checks on day one, with zero test files.

## How it works

The system is split across three layers, and the split is what keeps a dev-only package from leaking into production code:

**`plain.test` (core — always installed).** The authoring vocabulary: everything a test file imports. `Client` and `RequestFactory` (already there today), plus `raises`, the metadata decorators (`cases`, `skip`, `tag`, `timeout`), the context helpers (`override_settings`, `freeze_time`, `patch`, `capture_spans`, `capture_metrics`, `max_queries`), and the `TestLifecycle` protocol. These are small, dependency-light functions and context managers — none of them need the engine to exist. Keeping them in core means app code, package code, and type checkers never depend on a dev package, and `plain.test` remains the single import home you already know. It's also load-bearing outside of tests — `plain request` is built on `Client` — so it couldn't move to a dev-only package even if we wanted it to.

**`plain.testing` (this package — a dev dependency).** The engine: the `plain test` CLI, collection, assertion rewriting, execution and parallelism, flake classification, reporting (`--json`, route coverage, `--changed`), the browser wrapper, and the built-in suite. Nothing in your application imports from it; it imports *you*.

**Other Plain packages (lifecycle + helpers).** Each package that participates in testing implements the `TestLifecycle` protocol and registers it under the `plain.testing` entry point group:

```toml
# plain-postgres/pyproject.toml
[project.entry-points."plain.testing"]
postgres = "plain.postgres.test.lifecycle:PostgresTestLifecycle"
```

```python
class TestLifecycle:  # protocol, defined in plain.test
    def setup_worker(self): ...      # once per worker process
    def around_test(self, test): ... # context manager around each test
    def teardown_worker(self): ...
```

`plain.postgres` builds the template database and wraps each test in a lazy rolled-back transaction. `plain.email` resets the outbox. `plain.cache` isolates the cache. The engine discovers and drives them; the packages never import the engine. This entry point group is the **entire** extension API.

The dependency arrows only point one way:

```
your tests ──imports──▶ plain.test (core) + plain.<pkg>.test helpers
plain.testing (engine) ──drives──▶ lifecycle entry points ──live in──▶ each package
```

Since entry points are just strings in `pyproject.toml`, a package like `plain-postgres` declares its lifecycle without depending on `plain.testing` — the implementation is only imported when the engine runs it.

## Migrating from pytest

Test bodies survive untouched — bare `assert` and `Client` are the same. What changes is the machinery around them:

| pytest | plain.testing |
| --- | --- |
| `def test_x(db):` | `def test_x():` — database lifecycle is automatic |
| `settings` fixture | `with override_settings(...)` |
| `pytest.raises(...)` | `plain.test.raises(...)` |
| `pytest.mark.parametrize` | `@cases(...)` |
| `pytest.mark.skip` / custom marks | `@skip(...)` / `@tag(...)` |
| `monkeypatch` | `with patch(...)` |
| `otel_spans` / `otel_metrics` fixtures | `capture_spans()` / `capture_metrics()` |
| `conftest.py` fixtures | helper functions you import |
| `pytest-xdist` (`-n auto`) | built in |
| `pytest-asyncio` | built in |
| `pytest-randomly` | `--shuffle` |
| `pytest-timeout` | `--timeout` / `@timeout` |
| `pytest-rerunfailures` | flake classification (flaky stays red) |
| `freezegun` / `time-machine` | `freeze_time()` |
| `pytest-playwright` + `testbrowser` fixture | `testbrowser()` context manager |

The rewrites are mechanical, and the `/plain-upgrade` agent handles them. Anything it can't map — an un-absorbed pytest plugin, an unusual fixture — it reports instead of silently dropping.

`plain.pytest` remains available during the transition; the two runners can coexist in a project while you migrate.

## FAQs

#### Why is the package named `plain.testing` when I import from `plain.test`?

Because they're different things with different install lives. `plain.test` is a core module and has to stay one — it isn't only test vocabulary, core features depend on it at runtime (`plain request` simulates requests with `Client`). A dev-only package can't own a module that production Plain imports. So the module you import ships with core, and the engine that runs your tests installs separately. In practice: you **install** `plain.testing`, you **import** from `plain.test`, you **run** `plain test`.

#### Does coverage work?

Yes — `coverage run -m plain.testing` works like any other Python entry point, no plugin needed. Route coverage (`--route-coverage`) is separate and built in.

#### Can I use pytest plugins?

No — this is not pytest, and there is no plugin system to load them into. The most common plugins are features of the runner (see the migration table). If a plugin you rely on has no equivalent, that's useful feedback — and `plain.pytest` still exists.

#### How do I debug a failing test?

`plain test --pdb` drops into the debugger at the failure point. Every failure also prints its exact re-run command, so the loop is: copy, add `--pdb`, run.

#### What about my editor's test explorer?

Editors speak pytest's protocol, which this runner doesn't implement. `plain test --json` is the structured surface; editor integration would be its own project.

#### Why aren't there fixtures?

Fixtures solve a real problem — shared lifecycle — with an injection mechanism you can't see at the call site. The runner solves the same problem two other ways: framework-owned lifecycle for the infrastructure everyone needs (database, outbox, cache), and explicit imports for everything else. What's left over is ordinary Python.

## Installation

Install the `plain.testing` package from [PyPI](https://pypi.org/project/plain.testing/) as a dev dependency:

```bash
uv add plain.testing --dev
```

Then run your tests:

```bash
plain test
```

No configuration file is required. Tests are discovered in `tests/`, `.env.test` is loaded automatically, and installed Plain packages wire up their own test lifecycles.
