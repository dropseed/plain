# Testing

```
uv run plain test [targets] [options]
```

- `uv run plain test` - Run all tests (from the directory containing `tests/`)
- `uv run plain test tests/test_x.py::test_name` - Run one test
- `uv run plain test -k substring` - Filter by test id substring
- `uv run plain test -x` - Stop on first failure
- `uv run plain test -v` - One line per test
- `uv run plain test --tag slow` / `--exclude-tag slow` - Select by tag

## Writing tests

- Files `tests/**/test_*.py`; functions `test_*`; classes `Test*` with `test_*` methods (fresh instance per test, no setup_method).
- There are no fixtures and no conftest.py. A test function takes no parameters except the values `@cases` passes; one that does is a collection error. Shared setup is ordinary Python — helper functions the test calls in its body.
- Protection every test needs (no network, counters reset) goes in `tests/lifecycle.py`: one `TestLifecycle` subclass, found by path, wrapping every test. Never put setup a test reads there.
- Decorators declare static facts: `@cases(...)` (parametrize; wrap a case in `case(..., id="name")` to name it; one `@cases` per test), `@skip("reason")`, `@tag("name")` — from `plain.test`.
- To skip from inside a running test, call `skip_test("reason")`.
- Runtime state enters through `with` blocks: `override_settings(...)`, `patch(obj, "name", value)`, `capture_spans()`, `capture_metrics()`, `capture_logs()` — from `plain.test`.
- `raises(ExcType, match=...)` for expected exceptions; the caught exception is `caught.exception`.
- Bare `assert` everywhere — failures show both sides of comparisons.
- Database isolation is automatic (rolled-back transaction per test). DDL-heavy tests use `@isolated_db` from `plain.postgres.test`.
- Package helpers import from their package, and that package's docs cover them under Testing: `plain.email.test.outbox`, `plain.postgres.test.capture_queries` (SQL with values filled in) / `max_queries` / `span_sql_statements` (SQL as sent, `%s` placeholders kept), `plain.auth.test.login_client`, `plain.sessions.test.get_client_session`.
- Import a shared helper module by its path from where you run: `from tests.helpers import create_user`. Relative imports don't work in test files.
- `Client` (from `plain.test`) speaks request vocabulary: `form_data=`, `json_data=`, `query_params=`, `files=`, `body=`/`content_type=`; `follow_redirects=True`; responses expose `status_code`, `text`, `body`, `json_data`, `redirect_to`, `request`. `client.websocket(path)` opens a socket to a view's `websocket()` (`WebSocketRejected` if the handshake is refused).

Run `uv run plain docs testing` and `uv run plain docs test` for full documentation.
