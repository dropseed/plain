# plain-test changelog

## [0.1.0](https://github.com/dropseed/plain/releases/plain-test@0.1.0) (unreleased)

### What's changed

- `plain.test` is this package now, a dev dependency, and no longer part of Plain itself. It holds what a test file imports (`Client`, `raises`, `@cases`, the captures) and the runner behind `plain test`. `from plain.test import ...` reads the same as before.
- Initial working engine: collection (`test_*` functions, `Test*` classes, async tests), assertion rewriting for bare `assert`, `@cases` expansion, `@skip`, `@tag` selection (`--tag`/`--exclude-tag`), `-k`/`-x`/`-v`, and failure output ending in a re-run command.
- `plain test` CLI, contributed through the `plain.cli` entry point group so it is available without `plain.runtime.setup()` (and therefore outside an app). Because nothing has set the runtime up by the time it runs, the runner makes the app-vs-library decision itself. The runner reads no `.env` files itself: plain.dev loads `.env.test` from its setup hook, as it does for every command.
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
- A failed assert prints every value inside its expression, from the outside in, for any expression: a comparison, a call, a membership test, `and`/`or`/`not`. Each part is evaluated once and in order, and a part Python never evaluated is reported as not evaluated. The error raised is an ordinary `AssertionError`, with the test's message or none.
- Two large values that were expected to be equal are printed as a diff: text by line, dicts by key, lists by item, dataclasses by field.
- Every failure prints the test function's locals.
- A value is printed whole up to 2,000 characters and a diff up to 60 lines, and says how much was cut. `--full-values` prints everything. The 400-character and 20-item limits are gone.
- A lifecycle's `describe_value(value)` says how a failure prints a value its package owns. plain.postgres prints a model instance with its fields and a queryset with its SQL or its rows, and runs no query to do it.
- What a test writes to stdout and stderr is held while it runs, whatever writes it: `print()`, a log handler, a subprocess, a C extension. A test that fails has it printed with its failure, and a test that passes has it thrown away. `-s` (`--show-output`) lets it through as it is written. `breakpoint()` gets the terminal until its test is over.
- `plain test --json` prints one JSON document when the run is over, and nothing else on stdout: what was asked for, the counts, and each failed or skipped test. A failure carries its file and line, the traceback as frames, the values inside the assert, the diff, the test's locals, what the test wrote, and the re-run command. `--list-passed` lists the tests that passed too. A run that was interrupted or couldn't start prints a document as well.
- A run stopped with Ctrl-C reports the failures it had and what the running test had written, and exits `130`.
- A run that can't be set up says so and exits `3`: the app's setup or a lifecycle's `setup_worker()` raised, or wrote its reason and called `sys.exit()`, as creating the test database does when the server can't be reached. It prints what failed and what had been written, and `--json` prints a document with `stopped.reason` of `"setup_error"`. It used to end the run with a bare traceback or with nothing at all.
- What is written outside any test (setting up the app and the lifecycles, taking them down) is printed at the end of the run under `WRITTEN OUTSIDE ANY TEST`, and is the `--json` document's own `stdout` and `stderr`. It was thrown away.
- Warnings tests raise are counted in the summary and listed once each, with how many times each was raised and where first. `DeprecationWarning` and `PendingDeprecationWarning` are shown unless `-W` or `PYTHONWARNINGS` says otherwise.
- A failure report leaves out what is known to be a secret, in text and in `--json`, with `--full-values` too: `os.environ` prints its names, a dict prints without the items it took from the environment, and a model instance prints an encrypted field or a password as `<withheld>`. A field type says its value is one with `value_is_secret = True`.
- `describe_value()` is asked about values inside a list, a tuple, a dict or a set, at any depth, and not only about the value at the top.
- A large value a failure has under two names is printed once, and the second says which it is the same as. A failed assert's message is printed once, at the end of the traceback.
- A lifecycle that raises being taken down is reported after the run. A collection error names its file relative to where the run started, as a test's id does.
- Test modules are loaded through the import machinery, so they have a spec and a loader, and an instance of a class defined in one can be pickled. Their rewritten bytecode is cached under a name of its own in `__pycache__`.
- `CollectedTest`, what a lifecycle's `around_test(test)` receives, is in `plain.test`. Nothing in `plain.test.runner` is an importable API.
- `capture_spans`, `capture_metrics`, `capture_logs` and `plain.postgres.test.capture_queries` hand back one shape: a read-only sequence of what was captured, read after the block ends. Reading one inside its block raises. `spans.filter(name=, kind=)`, `metrics.number_points()` / `metrics.histogram_points()`, `logs.messages` and `queries.sql_statements()` are the finders. Captures can be nested.
- Captures nest, `capture_queries` and `max_queries` included: one opened inside another leaves the outer one whole. `CaptureSource` in `plain.test` is what a package's own capture helper is built on. Spans and metrics that nobody is capturing are dropped, not kept until the next capture.
- `patch` leaves the target holding what it held before: an instance or a class that only inherited the attribute inherits it again, a `staticmethod` is still one, and a property, a slot or a setting gets its value back.
- The tests that roll back share one database connection. Session-level state (a session advisory lock, a `LISTEN`) carries from one test to the next unless the test is `@isolated_db`.
- `capture_queries` records the statement as it was sent (`query.sql`) beside the one with its values filled in (`query.sql_with_params`), and sees queries that run with tracing suppressed.
- `skip_test(reason)` skips from inside a running test. Skipped tests are listed with their reasons and counted in the summary.
- A case is named for its values, `test_price[5-500]`, when every value of every case of the test is a string, a number, a boolean, `None` or an enum member and no two cases come out the same. Otherwise the test's cases are numbered. Every id in one `@cases` is different, or the decorator raises: a name given to one case could be what another was numbered, and the second was never run.
- Nothing that looks like a test is left out without a word. A `test_*` static or class method is run. A test with a `yield` in it, a `unittest.TestCase`, and a test function or class imported from another module are collection errors that say what to write. A test that yields used to be reported as passed with none of its body run.
- A test file that imports pytest is a collection error that says where, what the file uses from pytest, and what replaces each. It was a `ModuleNotFoundError` traceback.
- A collection error that many files share says what they share once. The first file carries it, and the rest say what is wrong with their own file. A `conftest.py` is reported before the files that used it.
- A test that takes fixtures is told what each parameter was: one of pytest's fixtures and what to write instead, or a fixture in a `conftest.py` the run found. A file with more than three such tests says how many.
- A `conftest.py` above the target is a collection error however the target is written. It was reported for a file and not for a directory.
- An import from a conftest says to import from the helper module the name moves to. It was told to import the conftest by its bare name.
- An assert with a starred subscript (`grid[*position]`) is rewritten into code that compiles. The file it was in couldn't be collected.
- Two roots with a test file of the same name load two modules. The second was handed the first's.
- Replaces `plain.pytest`. pytest is no longer supported, and there is no release where both run.

### Upgrade instructions

Replace the dev dependency and move the tests off pytest. Assertions don't change. What changes is how a test gets what it needs.

- In `pyproject.toml`, replace `plain.pytest` (and `pytest`, `pytest-*` plugins) with `plain.test` in your dev dependencies. Delete any `[tool.pytest.ini_options]` section and `pytest.ini`.
- `plain.test` used to come with Plain, so a project could import it with nothing installed. It doesn't any more. If anything outside your tests imports `plain.test`, add `plain.test` wherever that code's dependencies are declared.
- Run `plain agent install`, so that the project's own rule files say how tests are written now. Until then `.claude/rules/plain-test.md` still says to use pytest fixtures.
- Run `plain test`. A half-migrated suite says what is left, each thing once: each `conftest.py` with the fixtures it defines, each file that imports pytest with what it uses and what replaces it, and each file whose tests still take fixtures with what every parameter was.
- Move what each `conftest.py` holds, then delete the file. Fixtures tests ask for become functions in a helper module such as `tests/helpers.py`. Autouse fixtures that protected every test become `tests/lifecycle.py`.
- Import helper modules by their bare names: `from helpers import create_user`, not `from tests.helpers import ...` or `from .helpers import ...`, and nothing from `conftest`.
- A case's id is its values again, as pytest named it: `test_price[5-500]`. A `-k` or a target written against a numbered id (`test_price[0]`) needs the new one.
- `plain request` now comes from `plain.dev`, not Plain itself. Nothing to change if `plain.dev` is in your dev dependencies, which it is in a project made with `plain-start`. The command, its flags and its output are the same.

What replaces each fixture, mark, helper and client call is in the README, under "Migrating from pytest": `plain docs test --search "Migrating from pytest"`. The errors `plain test` prints for a file that imports pytest point there too.
