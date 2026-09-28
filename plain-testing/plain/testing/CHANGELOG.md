# plain-testing changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-testing@0.1.0) (unreleased)

### What's changed

- Initial working engine: collection (`test_*` functions, `Test*` classes, async tests), assertion rewriting for bare `assert` with left/right values on failure, `@cases` expansion, `@skip`, `@tag` selection (`--tag`/`--exclude-tag`), `-k`/`-x`/`-v`, and failure output ending in a re-run command.
- `plain test` CLI, contributed through the `plain.cli` entry point group so it is available without `plain.runtime.setup()` (and therefore outside an app). Because nothing has set the runtime up by the time it runs, the runner makes the app-vs-library decision itself. `.env.test` loads via plain.dev's ladder when installed, with a minimal fallback otherwise.
- Test lifecycle extension point: packages register a `TestLifecycle` under the `plain.testing` entry point group. plain.postgres provides the automatic test database with per-test rolled-back transactions and `@isolated_db`; plain.email routes to the locmem backend and clears the outbox per test.
- A project declares its own lifecycle in `tests/lifecycle.py`: one `TestLifecycle` subclass, found by its path, entered after the packages' lifecycles so it wraps closest to the test. A file that is there but doesn't hold exactly one usable lifecycle stops the run before any test.
- Tests that can't run as written are rejected at collection, all of a file's at once: a test with parameters nothing passes in (there are no fixtures), a case with the wrong number of values, a second `@cases` on one test, a bare `@skip` or `@tag`.
- `skip_test(reason)` skips from inside a running test. Skipped tests are listed with their reasons and counted in the summary.
- Replaces `plain.pytest`. pytest is no longer supported, and there is no release where both run.

### Upgrade instructions

Replace the dev dependency and move the tests off pytest. Assertions don't change. What changes is how a test gets what it needs.

- In `pyproject.toml`, replace `plain.pytest` (and `pytest`, `pytest-*` plugins) with `plain.testing`. Delete any `[tool.pytest.ini_options]` section, `pytest.ini`, and `conftest.py` files once their contents have moved. A leftover `conftest.py` is not loaded and nothing says so.
- Run `plain test`. A test that still asks for a fixture is rejected when its file is collected, with the test and its parameters named, so a half-migrated suite says what is left.

Fixtures:

| pytest                                              | Now                                                                                                                  |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `def test_x(db):`, `@pytest.mark.usefixtures("db")` | `def test_x():`. Every test already runs in a rolled-back transaction                                                |
| `isolated_db` fixture                               | `@isolated_db` from `plain.postgres.test`                                                                            |
| a fixture a test reads (`user`, `client`)           | a function the test calls in its body: `user = create_user()`                                                        |
| a fixture with teardown (`yield`)                   | a `@contextmanager` function the test enters with `with`                                                             |
| a fixture that returns a factory (`make_user`)      | the factory itself, imported                                                                                         |
| `conftest.py`                                       | a module you import: `from tests.helpers import create_user`                                                         |
| an autouse fixture that protects every test         | `tests/lifecycle.py`, one `TestLifecycle` subclass                                                                   |
| an autouse fixture that sets up one file            | an explicit `with helper():` in each test that needs it                                                              |
| `setup_method` / `teardown_method`                  | the same: a context manager the test enters. A `Test*` class gets a fresh instance per test and has no setup methods |
| `settings` fixture                                  | `with override_settings(NAME=value):`                                                                                |
| `monkeypatch.setattr(obj, "name", value)`           | `with patch(obj, "name", value):`. It takes the object, not a dotted string                                          |
| `monkeypatch.setenv("KEY", "value")`, `setitem`     | `with patch(os.environ, "KEY", "value"):`                                                                            |
| `monkeypatch.delenv`, `delattr`                     | no equivalent. Use `unittest.mock.patch.dict(os.environ)` and delete inside it                                       |
| `otel_spans` / `otel_metrics`                       | `with capture_spans() as spans:` / `with capture_metrics() as metrics:`                                              |
| `caplog`                                            | `with capture_logs() as logs:`                                                                                       |
| `capsys`                                            | `with contextlib.redirect_stdout(io.StringIO()) as out:`                                                             |
| `tmp_path`                                          | `with tempfile.TemporaryDirectory() as tmp:` then `Path(tmp)`                                                        |
| `mailoutbox` / the email outbox fixture             | `from plain.email.test import outbox`                                                                                |

Marks and helpers:

| pytest                                         | Now                                                                            |
| ---------------------------------------------- | ------------------------------------------------------------------------------ |
| `pytest.raises(E, match=...)`, `excinfo.value` | `raises(E, match=...)`, `caught.exception`, readable after the block           |
| `pytest.mark.parametrize("a,b", [...])`        | `@cases((a, b), (a, b))`. A single value is passed bare                        |
| `pytest.param(..., id="x")`, `ids=[...]`       | `case(..., id="x")` inside `@cases`                                            |
| stacked `parametrize`                          | one `@cases(*itertools.product(FIRST, SECOND))`                                |
| `pytest.mark.skip(reason=...)`                 | `@skip("reason")`. The reason is required                                      |
| `pytest.mark.skipif(condition, ...)`           | `if condition: skip_test("reason")` as the test's first line                   |
| `pytest.skip("reason")` in a test              | `skip_test("reason")`                                                          |
| custom marks, `-m slow`                        | `@tag("slow")`, `--tag slow`                                                   |
| `pytest.mark.xfail`                            | no equivalent. `@skip` it with the reason, or assert the failure with `raises` |
| `pytest.approx(x, abs=...)`                    | `math.isclose(a, x, abs_tol=...)` inside a bare `assert`                       |
| `pytest-asyncio`                               | nothing. `async def test_*` runs as written                                    |

The test client, where everything after the path is now keyword-only:

| Before                                            | Now                                                             |
| ------------------------------------------------- | --------------------------------------------------------------- |
| `client.post(path, {...})`, `data={...}`          | `form_data={...}`                                               |
| `data=x, content_type="application/json"`         | `json_data=x`                                                   |
| raw bytes with a content type                     | `body=b"...", content_type="..."`                               |
| `client.get(path, {...})`                         | `query_params={...}`                                            |
| `follow=True`                                     | `follow_redirects=True`                                         |
| `response.content`                                | `response.body` for bytes, `response.text` for a string         |
| `response.content.decode()`                       | `response.text`                                                 |
| `response.json()`, `json.loads(response.content)` | `response.json_data`                                            |
| `response.url` on a redirect                      | `response.redirect_to`                                          |
| `response.user`                                   | `get_request_user(response.request)` from `plain.auth.requests` |
| `RequestFactory().generic("PUT", "/x")`           | `RequestFactory().request(method="PUT", path="/x")`             |

Only the test client's response changes. `content` on a `Response` your own code builds or a view returns is unchanged.

Plugins with no replacement yet:

- `pytest-xdist`: tests run in one process. Drop `-n`.
- `pytest-randomly`, `pytest-rerunfailures`: no equivalent. Tests run in a fixed order, once.
- `pytest-timeout`: no equivalent.
- `pytest-playwright` and the `testbrowser` fixture: no equivalent. Browser tests can't be migrated yet.
- `pytest-mock`: use `unittest.mock` directly, or `patch` from `plain.test`.
- `pytest-cov`: `coverage run -m plain.testing`, then `coverage report`.
- `freezegun`, `time-machine`, `hypothesis`: these are libraries, not plugins. They keep working.
- Editor test explorers speak pytest's protocol and won't find these tests.
