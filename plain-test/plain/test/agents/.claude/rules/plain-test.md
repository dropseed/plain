# Testing

```
uv run plain test [targets] [options]
```

- `uv run plain test` - Run all tests (from the directory containing `tests/`)
- `uv run plain test tests/test_x.py::test_name` - Run one test
- `uv run plain test --match text` - Run the tests whose id contains the text (as written: not a pattern, not an expression)
- `uv run plain test --fail-fast` - Stop on first failure
- `uv run plain test --verbose` - One line per test. Without it a test that passes prints nothing: a run that passes is the collected count and the summary
- `uv run plain test --tag slow` / `--exclude-tag slow` - Select by tag
- `uv run plain test --full-values` - Print every value in a failure whole
- `uv run plain test --json` - One JSON document on stdout when the run is over: counts, and for each failure its file and line, the values inside the assert, the diff, the test's locals, what it wrote, and the re-run command. Passing tests are counted, not listed (`--list-passed` lists them)
- `uv run plain test --show-output` - Let what tests print and log through as it's written. Without it output is held: a failing test's is printed with its failure, a passing test's is thrown away
- Exit codes: `0` passed, `1` a test failed or a file couldn't be collected, `2` the command can't be used as given, `3` setting up failed and no test was run (the database can't be reached: fix that, not the tests), `4` no tests matched, `130` interrupted

## Writing tests

- Files `tests/**/test_*.py`; functions `test_*`; classes `Test*` with `test_*` methods (fresh instance per test, no setup_method). Define a test in the file that runs it. A test with a `yield` in it is a collection error: none of its body would run.
- Nothing is passed to a test by name, and no file but `test_*.py` and `tests/lifecycle.py` is read. A test function takes no parameters except the values `@cases` passes; one that does is a collection error. Shared setup is ordinary Python — helper functions the test calls in its body.
- Protection every test needs (no network, counters reset) goes in `tests/lifecycle.py`: one `TestLifecycle` subclass, found by that exact path, wrapping every test. Never put setup a test reads there.
- Decorators declare static facts: `@cases(...)` (the test runs once for each case; one `@cases` per test), `@skip("reason")`, `@tag("name")` — from `plain.test`. A case is reported by its values, `test_price[5-500]`, when they are all strings, numbers, booleans, `None` or enum members, and numbered otherwise; wrap one in `case(..., id="name")` to name it.
- To skip from inside a running test, call `skip_test("reason")`.
- Runtime state enters through `with` blocks: `override_settings(...)`, `patch(obj, "name", value)`, `capture_spans()`, `capture_metrics()`, `capture_logs()` — from `plain.test`.
- A `capture_*` block hands back a read-only sequence (`len()`, indexing, iteration). Read it after the `with` block ends — reading inside raises. Finders: `spans.filter(name=, kind=)`, `metrics.number_points(name, attributes=)` / `metrics.histogram_points(name, attributes=)`, `logs.messages`.
- `raises(ExcType, match=...)` for expected exceptions; the caught exception is `caught.exception`.
- Bare `assert` everywhere. A failure prints every value inside the expression, a diff of two large values, and the test's locals, so don't add values to the assert: no `assert x == y, f"{x} != {y}"`, no `print()` before it. A message after the comma is for saying why.
- A value in a failure is cut at 2,000 characters; `--full-values` prints it whole.
- A failure report withholds what is known to be a secret (`os.environ`'s values, a model's password or encrypted field). A secret held in a plain string is printed, so don't put one in an assert or a local: compare against a value the test made up.
- Database isolation is automatic (rolled-back transaction per test). DDL-heavy tests use `@isolated_db` from `plain.postgres.test`.
- Package helpers import from their package, and that package's docs cover them under Testing: `plain.email.test.outbox`, `plain.postgres.test.capture_queries` (each query has `.sql` as sent and `.sql_with_params`; `queries.sql_statements(table=)` to pin statements) / `max_queries`, `plain.auth.test.login_client`, `plain.sessions.test.get_client_session`.
- Import a shared helper module by its bare name: `tests/helpers.py` is `from helpers import create_user`, from any test file. `from tests.helpers import ...` and relative imports are collection errors.
- `Client` (from `plain.test`) speaks request vocabulary: `form_data=`, `json_data=`, `query_params=`, `files=`, `body=`/`content_type=`; `follow_redirects=True`; responses have a fixed set of names (`status_code`, `headers`, `body`, `text`, `json_data`, `redirect_to`, `request`, …) and `returned_response` for the `Response` the view returned. Log a client in with `login_client(client, user)` from `plain.auth.test`; read its session with `get_client_session(client)` from `plain.sessions.test`. `client.websocket(path)` opens a socket to a view's `websocket()` (`WebSocketRejected` if the handshake is refused). A path goes to `https://testserver`; pass a full URL (`http://testserver/x`) when the scheme or host matters. `Client(raise_exceptions=False)` returns the 5xx instead of raising what the view raised.
- `build_request(method, path, ...)` (from `plain.test`) builds a `Request` without sending it, with the client's keywords, for calling a view or middleware directly. There is no `RequestFactory`.

Run `uv run plain docs test` for full documentation. `plain.test` is a dev dependency (`uv add plain.test --dev`), not part of Plain itself.
