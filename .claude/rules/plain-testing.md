# Testing

```
uv run plain test [targets] [options]
```

- `uv run plain test` - Run all tests (from the directory containing `tests/`)
- `uv run plain test tests/test_x.py::test_name` - Run one test
- `uv run plain test tests/test_x.py:42` - Run the test line 42 is in, which is what a traceback gives you
- `uv run plain test --match text` - Run the tests whose id contains the text (as written: not a pattern, not an expression)
- `uv run plain test --fail-fast` - Stop on first failure
- `uv run plain test --verbose` - One line per test. Without it a test that passes prints nothing: a run that passes is the collected count and the summary
- `uv run plain test --tag slow` / `--exclude-tag slow` - Select by tag
- `uv run plain test --full-values` - Print every value in a failure whole
- `uv run plain test --json` - One JSON document on stdout when the run is over: counts, and for each failure its file and line, the values inside the assert, the diff, the test's locals, what it wrote, and the re-run command. Passing tests are counted, not listed (`--list-passed` lists them)
- `uv run plain test --show-output` - Let what tests print and log through as it's written. Without it output is held: a failing test's is printed with its failure, a passing test's is thrown away
- Exit codes: `0` passed, `1` a test failed or a file couldn't be collected, `2` the command can't be used as given, `3` setting up failed and no test was run (the database can't be reached: fix that, not the tests), `4` no tests matched, `130` interrupted

## Writing tests

- Files `tests/**/test_*.py`; functions `test_*`. Tests live in `tests/`, beside `app/`: a `test_*.py` in `app/` that has tests in it is not run, and is a collection error. A test is a function and a file is the group: a class with `test_*` methods in it is a collection error. Define a test in the file that runs it. A test with a `yield` in it is a collection error: none of its body would run.
- Nothing is passed to a test by name, and no file but `test_*.py` and `tests/lifecycle.py` is read. A test function takes no parameters except the values `@cases` passes; one that does is a collection error. Shared setup is ordinary Python — helper functions the test calls in its body.
- Protection every test needs (no network, counters reset) goes in `tests/lifecycle.py`: one `TestLifecycle` subclass, found by that exact path, wrapping every test in the suite. There is none for a directory or a file. If a test's assertions depend on the thing, it is setup and goes in the test's body, even when every test in a directory needs it: a setting pinned for some tests is a `with override_settings(...)`, or a helper they enter, in each.
- Decorators declare static facts: `@cases(...)` (the test runs once for each case; one `@cases` per test), `@skip("reason")`, `@tag("name")` — from `plain.testing`. A case is reported by its values, `test_price[5-500]`, when they are all strings, numbers, booleans, `None` or enum members, and numbered otherwise; wrap one in `case(..., id="name")` to name it.
- To skip from inside a running test, call `skip_test("reason")`.
- Runtime state enters through `with` blocks: `override_settings(...)`, `patch(obj, "name", value)`, `capture_spans()`, `capture_metrics()`, `capture_logs()` — from `plain.testing`.
- A `capture_*` block hands back a read-only sequence (`len()`, indexing, iteration). Read it after the `with` block ends — reading inside raises. Finders: `spans.filter(name=, kind=)`, `metrics.number_points(name, attributes=)` / `metrics.histogram_points(name, attributes=)`, `logs.messages`.
- `raises(ExcType, match=...)` for expected exceptions; the caught exception is `caught.exception`.
- Bare `assert` everywhere. A failure prints every value inside the expression, a diff of two large values, and the test's locals, so don't add values to the assert: no `assert x == y, f"{x} != {y}"`, no `print()` before it. A message after the comma is for saying why.
- A value in a failure is cut at 2,000 characters; `--full-values` prints it whole.
- A failure report withholds what is known to be a secret (`os.environ`'s values, a model's password or encrypted field). A secret held in a plain string is printed, so don't put one in an assert or a local: compare against a value the test made up.
- Database isolation is automatic (rolled-back transaction per test). DDL-heavy tests use `@isolated_db` from `plain.postgres.test`.
- Package helpers import from their package, and that package's docs cover them under Testing: `plain.email.test.outbox`, `plain.postgres.test.capture_queries` (each query has `.sql` as sent and `.sql_with_params`; `queries.sql_statements(table=)` to pin statements) / `max_queries`, `plain.auth.test.login_client`, `plain.sessions.test.get_client_session`.
- Import a helper module by its path from `tests/`, from any test file: `tests/helpers.py` is `from helpers import create_user`, and `tests/billing/refund_helpers.py` is `from billing.refund_helpers import create_refund`. No `__init__.py` is needed. `from tests.helpers import ...`, a relative import, and a module further down imported by the end of its path are collection errors that say what to write.
- `Client` (from `plain.testing`) speaks request vocabulary: `form_data=`, `json_data=`, `query_params=`, `files=`, `body=`/`content_type=`; `follow_redirects=True`; responses have a fixed set of names (`status_code`, `headers`, `body`, `text`, `json_data`, `redirect_to`, `request`, …) and `returned_response` for the `Response` the view returned. Log a client in with `login_client(client, user)` from `plain.auth.test`; read its session with `get_client_session(client)` from `plain.sessions.test`. `client.websocket(path)` opens a socket to a view's `websocket()` (`WebSocketRejected` if the handshake is refused). A path goes to `https://testserver`; pass a full URL (`http://testserver/x`) when the scheme or host matters. `Client(raise_exceptions=False)` returns the 5xx instead of raising what the view raised.
- `build_request(method, path, ...)` (from `plain.testing`) builds a `Request` without sending it, with the client's keywords, for calling a view or middleware directly. There is no `RequestFactory`.

Run `uv run plain docs testing` for full documentation. `plain.testing` is a dev dependency (`uv add plain.testing --dev`), not part of Plain itself.
