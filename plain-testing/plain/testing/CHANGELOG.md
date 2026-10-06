# plain-testing changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-testing@0.1.0) (2026-10-06)

### What's changed

- First release. `plain.testing` is Plain's own test runner and the test client, replacing `plain.pytest`. A test is a function in `tests/**/test_*.py` that makes a bare `assert`; a file is the group, and there are no test classes, fixtures or `conftest.py`. `Client` makes a request to the app in-process and returns the response that would have been sent, with `form_data=`, `json_data=`, `query_params=`, `files=` and the rest of the request vocabulary, and `client.websocket()` for WebSocket views. `@cases`, `@skip` and `@tag` attach static facts; `override_settings`, `patch`, `raises`, `skip_test` and the captures (`capture_spans`, `capture_metrics`, `capture_logs`) are used in the body. Installed packages protect every test through a `TestLifecycle` (plain.postgres rolls each test back, plain.email resets the outbox) and a project adds its own in `tests/lifecycle.py` ([2278c086af](https://github.com/dropseed/plain/commit/2278c086af))
- `plain test` runs them: a target is a directory, a file, a test (`tests/test_x.py::test_name`) or a line (`tests/test_x.py:42`); `--match`, `--tag`, `--exclude-tag`, `--fail-fast`, `--verbose`, `--show-output`, `--full-values`, `--json` and `--list-passed`, each with one name. A run that passes prints two lines. A failure prints every value inside the assert, a diff for large values, the test's locals, what the test wrote, and the command that runs it again; `--json` renders the same run as one document. Exit codes run `0` to `4`, and `130` ([2278c086af](https://github.com/dropseed/plain/commit/2278c086af))
- A run reports where its time went, under `--verbose` or whenever more than a second is spent outside the tests: imports, each setup hook, the test database, the tests. The report is always in `--json` ([2278c086af](https://github.com/dropseed/plain/commit/2278c086af))
- Requires `plain>=0.166.0`, which has the in-process server the client is built on ([2278c086af](https://github.com/dropseed/plain/commit/2278c086af))

### Upgrade instructions

- `uv add plain.testing --dev`, then `plain agent install`. Moving a suite from pytest is described step by step in the [pull request that introduced the package](https://github.com/dropseed/plain/pull/130): dependencies, rule files, commands and flags, what `conftest.py` guarded against, fixtures, classes, the client, and what the first run reports.
