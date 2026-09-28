# plain-test changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-test@0.1.0) (unreleased)

### What's changed

- `plain.test` is this package now, a dev dependency, and no longer part of Plain itself. It holds what a test file imports (`Client`, `raises`, `@cases`, the captures) and the runner behind `plain test`. `from plain.test import ...` reads the same as before.
- Initial working engine: collection (`test_*` functions, `Test*` classes, async tests), assertion rewriting for bare `assert` with left/right values on failure, `@cases` expansion, `@skip`, `@tag` selection (`--tag`/`--exclude-tag`), `-k`/`-x`/`-v`, and failure output ending in a re-run command.
- `plain test` CLI, contributed through the `plain.cli` entry point group so it is available without `plain.runtime.setup()` (and therefore outside an app). Because nothing has set the runtime up by the time it runs, the runner makes the app-vs-library decision itself. `.env.test` loads via plain.dev's ladder when installed, with a minimal fallback otherwise.
- Test lifecycle extension point: packages register a `TestLifecycle` under the `plain.test` entry point group. plain.postgres provides the automatic test database with per-test rolled-back transactions and `@isolated_db`; plain.email routes to the locmem backend and clears the outbox per test.
- A project declares its own lifecycle in `tests/lifecycle.py`: one `TestLifecycle` subclass, found by its path, entered after the packages' lifecycles so it wraps closest to the test. A file that is there but doesn't hold exactly one usable lifecycle stops the run before any test.
- Tests that can't run as written are rejected at collection, all of a file's at once: a test with parameters nothing passes in (there are no fixtures), a case with the wrong number of values, a second `@cases` on one test, a bare `@skip` or `@tag`.
- A `conftest.py` anywhere under the tests is a collection error that lists the fixtures it defines and says where each kind goes.
- Every way of writing a test the runner can't run is one error, `TestDefinitionError`, printed as its message with the line it was raised on. Any other error in a test file, or in `tests/lifecycle.py`, is printed with its traceback, starting at that file.
- A helper module is imported by its bare name (`tests/helpers.py` is `helpers`) from any test file, wherever the command runs from. An import through `tests.` or a relative import is a collection error that gives the import to write.
- A project lifecycle in a file the runner doesn't read (`tests/lifecycles.py`, `lifecycle.py` beside `tests/`) stops the run and says where it belongs.
- `plain test --help` lists the flags and the forms a target takes.
- The re-run command a failure prints is quoted for the shell, so a case id with spaces, brackets or `$` can be pasted.
- A failed assertion shows the expression as the test wrote it. It was regenerated from the syntax tree, which dropped parentheses.
- `CollectedTest`, what a lifecycle's `around_test(test)` receives, is in `plain.test`. Nothing in `plain.test.runner` is an importable API.
- `capture_spans`, `capture_metrics`, `capture_logs` and `plain.postgres.test.capture_queries` hand back one shape: a read-only sequence of what was captured, read after the block ends. Reading one inside its block raises. `spans.filter(name=, kind=)`, `metrics.number_points()` / `metrics.histogram_points()`, `logs.messages` and `queries.sql_statements()` are the finders. Captures can be nested.
- `capture_queries` records the statement as it was sent (`query.sql`) beside the one with its values filled in (`query.sql_with_params`), and sees queries that run with tracing suppressed.
- `skip_test(reason)` skips from inside a running test. Skipped tests are listed with their reasons and counted in the summary.
- Replaces `plain.pytest`. pytest is no longer supported, and there is no release where both run.

### Upgrade instructions

Replace the dev dependency and move the tests off pytest. Assertions don't change. What changes is how a test gets what it needs.

- In `pyproject.toml`, replace `plain.pytest` (and `pytest`, `pytest-*` plugins) with `plain.test` in your dev dependencies. Delete any `[tool.pytest.ini_options]` section and `pytest.ini`.
- `plain.test` used to come with Plain, so a project could import it with nothing installed. It doesn't any more. If anything outside your tests imports `plain.test`, add `plain.test` wherever that code's dependencies are declared.
- Run `plain test`. A half-migrated suite says what is left: each `conftest.py` is reported with the fixtures it defines, and a test that still asks for a fixture is rejected when its file is collected, with the test and its parameters named.
- Move what each `conftest.py` holds, then delete the file. Fixtures tests ask for become functions in a helper module such as `tests/helpers.py`. Autouse fixtures that protected every test become `tests/lifecycle.py`.
- Import helper modules by their bare names: `from helpers import create_user`, not `from tests.helpers import ...` or `from .helpers import ...`.
- `plain request` now comes from `plain.dev`, not Plain itself. Nothing to change if `plain.dev` is in your dev dependencies, which it is in a project made with `plain-start`. The command, its flags and its output are the same.

Fixtures:

| pytest                                              | Now                                                                                                                  |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `def test_x(db):`, `@pytest.mark.usefixtures("db")` | `def test_x():`. Every test already runs in a rolled-back transaction                                                |
| `isolated_db` fixture                               | `@isolated_db` from `plain.postgres.test`                                                                            |
| a fixture a test reads (`user`, `client`)           | a function the test calls in its body: `user = create_user()`                                                        |
| a fixture with teardown (`yield`)                   | a `@contextmanager` function the test enters with `with`                                                             |
| a fixture that returns a factory (`make_user`)      | the factory itself, imported                                                                                         |
| `conftest.py`                                       | a module you import: `tests/helpers.py`, as `from helpers import create_user`                                        |
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

Spans, metrics, logs and queries. Each `capture_*` block hands back a read-only sequence, and it's read after the block ends:

| Before                                                          | Now                                                                                        |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `otel_spans.get_finished_spans()`                               | `spans` itself: `len(spans)`, `spans[0]`, `for span in spans`                              |
| `[s for s in otel_spans.get_finished_spans() if s.name == "x"]` | `spans.filter(name="x")`. It also takes `kind=`                                            |
| `otel_spans.get_finished_spans() == ()`                         | `list(spans) == []`                                                                        |
| `otel_spans.clear()` after the setup                            | open `with capture_spans() as spans:` after the setup                                      |
| `otel_metrics.get_metrics_data()`, walked down to data points   | `metrics.number_points(name)` or `metrics.histogram_points(name)`                          |
| filtering those points by an attribute                          | `attributes={"key": "value"}` on either                                                    |
| `otel_metrics.collect()`                                        | nothing. Metrics are collected when the block ends                                         |
| `caplog.records`, `caplog.messages`                             | `logs` itself, and `logs.messages`                                                         |
| reading any of them partway through the test                    | end the block first. Reading a capture inside its block raises                             |
| `queries[0]["sql"]` from `capture_queries`                      | `queries[0].sql_with_params`, or `queries[0].sql` for the statement with its `%s` in place |
| a hand-written `execute_wrapper` that records statements        | `queries.sql_statements()` from `capture_queries`                                          |
| `install_test_tracer()`, `install_test_meter()`                 | gone. `capture_spans()` and `capture_metrics()` install what they need                     |

The test client, where everything after the path is now keyword-only:

| Before                                            | Now                                                                         |
| ------------------------------------------------- | --------------------------------------------------------------------------- |
| `client.post(path, {...})`, `data={...}`          | `form_data={...}`                                                           |
| `data=x, content_type="application/json"`         | `json_data=x`                                                               |
| raw bytes with a content type                     | `body=b"...", content_type="..."`                                           |
| `client.get(path, {...})`                         | `query_params={...}`                                                        |
| `follow=True`                                     | `follow_redirects=True`                                                     |
| `response.content`                                | `response.body` for bytes, `response.text` for a string                     |
| `response.content.decode()`                       | `response.text`                                                             |
| `response.json()`, `json.loads(response.content)` | `response.json_data`                                                        |
| `response.url` on a redirect                      | `response.redirect_to`                                                      |
| `response.user`                                   | `get_request_user(response.request)` from `plain.auth.requests`             |
| `RequestFactory().get("/x")`, `.post("/x", ...)`  | `build_request("GET", "/x")`, `build_request("POST", "/x", ...)`            |
| `RequestFactory().generic("PUT", "/x")`           | `build_request("PUT", "/x")`                                                |
| `RequestFactory().request(data=, query_string=)`  | the client's keywords: `body=`, `form_data=`, `json_data=`, `query_params=` |
| `RequestFactory(headers=...)`, `factory.cookies`  | `headers=` on each `build_request()`, with a `Cookie` header for cookies    |
| `RequestFactory(json_encoder=...)`                | gone. Encode it yourself and pass `body=`                                   |
| `secure=False`                                    | a full URL: `client.get("http://testserver/x")`                             |
| `server_name=`, `server_port=`                    | a full URL: `client.get("https://example.com:8443/x")`                      |
| `Client(raise_request_exception=False)`           | `Client(raise_exceptions=False)`                                            |
| `client.trace(path)`                              | `client.request("TRACE", path)`, for any method                             |
| `client.request(request)` with a built `Request`  | `client.request(method, path, ...)`                                         |
| `client.force_login(user)`                        | `login_client(client, user)` from `plain.auth.test`                         |
| `client.logout()`                                 | `logout_client(client)` from `plain.auth.test`                              |
| `client.session`                                  | `get_client_session(client)` from `plain.sessions.test`                     |
| `client.cookies = SimpleCookie()`                 | `client.cookies.clear()`                                                    |
| `ws.response.request`                             | `ws.request`                                                                |
| any other attribute of the view's response        | `response.returned_response.<name>`                                         |

Only the test client's response changes. `content` on a `Response` your own code builds or a view returns is unchanged.

The client's response has a fixed set of names and no longer passes anything else through to the response the view returned: `status_code`, `headers`, `cookies`, `body`, `text`, `json_data`, `redirect_to`, `redirect_chain`, `request`, `exception`, `streaming`, `resolver_match`, and `returned_response`. Reading another name raises an `AttributeError` that lists them. `WebSocketRejected.response` is one of these too.

Plugins with no replacement yet:

- `pytest-xdist`: tests run in one process. Drop `-n`.
- `pytest-randomly`, `pytest-rerunfailures`: no equivalent. Tests run in a fixed order, once.
- `pytest-timeout`: no equivalent.
- `pytest-playwright` and the `testbrowser` fixture: no equivalent. Browser tests can't be migrated yet.
- `pytest-mock`: use `unittest.mock` directly, or `patch` from `plain.test`.
- `pytest-cov`: `coverage run -m plain.test`, then `coverage report`.
- `freezegun`, `time-machine`, `hypothesis`: these are libraries, not plugins. They keep working.
- Editor test explorers speak pytest's protocol and won't find these tests.
