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
- There are no fixtures and no conftest.py. Shared setup is ordinary Python — helper modules at the tests root, imported explicitly.
- Decorators declare static facts: `@cases(...)` (parametrize), `@skip("reason")`, `@tag("name")` — from `plain.test`.
- Runtime state enters through `with` blocks: `override_settings(...)`, `patch(obj, "name", value)`, `capture_spans()`, `capture_metrics()` — from `plain.test`.
- `raises(ExcType, match=...)` for expected exceptions; the caught exception is `caught.exception`.
- Bare `assert` everywhere — failures show both sides of comparisons.
- Database isolation is automatic (rolled-back transaction per test). DDL-heavy tests use `@isolated_db` from `plain.postgres.test`.
- Package helpers import from their package: `plain.email.test.outbox`, `plain.postgres.test.capture_queries` / `max_queries`.
- `Client` (from `plain.test`) speaks request vocabulary: `form_data=`, `json_data=`, `query_params=`, `files=`, `body=`/`content_type=`; `follow_redirects=True`; responses expose `status_code`, `text`, `body`, `json_data`, `redirect_to`, `request`.

Run `uv run plain docs testing` and `uv run plain docs test` for full documentation.
