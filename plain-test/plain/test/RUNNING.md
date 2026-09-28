# plain.testing

**Plain's own test runner: plain functions, bare asserts, and nothing a test depends on that you can't see in its file.**

- [Overview](#overview)
- [Running tests](#running-tests)
    - [Selecting tests](#selecting-tests)
    - [Exit codes](#exit-codes)
    - [Environment](#environment)
- [Where tests live](#where-tests-live)
    - [Shared helpers](#shared-helpers)
- [Reading the output](#reading-the-output)
    - [Failures](#failures)
    - [Skipped tests](#skipped-tests)
    - [Collection errors](#collection-errors)
- [Assertions](#assertions)
- [What packages do for every test](#what-packages-do-for-every-test)
- [Project lifecycle](#project-lifecycle)
- [Testing code outside the app](#testing-code-outside-the-app)
- [How it works](#how-it-works)
- [Design rules](#design-rules)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

A test is a function that makes an assertion.

```python
# tests/test_homepage.py
from plain.test import Client


def test_homepage():
    response = Client().get("/")
    assert response.status_code == 200
```

Run it with `plain test`:

```
$ plain test
Collected 1 test
.

1 passed in 0.04s
```

Everything a test uses is an import, a call, or a `with` block in its own file. The one exception is protection the runner gives every test without being asked, like wrapping it in a database transaction. If you can read the test file, you know what happens.

This package is the runner. What a test file imports (the client, `raises`, `@cases`, `patch` and the rest) is [plain.test](../../../plain/plain/test/README.md), which ships with Plain itself.

## Running tests

```bash
plain test                                      # everything under the current directory
plain test tests/test_views.py                  # one file
plain test tests/checkout                       # one directory
plain test tests/test_views.py::test_homepage   # one test
plain test -k signup                            # tests whose id contains "signup"
plain test --tag slow                           # only tests tagged "slow"
plain test --exclude-tag slow                   # everything but
plain test -x                                   # stop at the first failure
plain test -v                                   # one line per test, with its duration
```

| Flag                 | What it does                                          |
| -------------------- | ----------------------------------------------------- |
| `-k TEXT`            | Keep the tests whose id contains `TEXT`               |
| `--tag NAME`         | Keep the tests with this tag. Repeat it to allow more |
| `--exclude-tag NAME` | Drop the tests with this tag. Repeat it to drop more  |
| `-x`, `--fail-fast`  | Stop at the first failure                             |
| `-v`, `--verbose`    | Print one line per test                               |

`plain test --help` prints the same list, and the forms a target can take.

Tests run in the same order every time. Within a file, that's the order they're written in.

### Selecting tests

A target is a path, optionally followed by `::` and a name. You can pass several.

| Target                                     | Runs                                 |
| ------------------------------------------ | ------------------------------------ |
| `tests/checkout`                           | Every test file under that directory |
| `tests/test_views.py`                      | Every test in that file              |
| `tests/test_views.py::test_homepage`       | That test, and every case of it      |
| `tests/test_views.py::TestCart`            | Every test in that class             |
| `tests/test_views.py::TestCart::test_add`  | That method                          |
| `'tests/test_email.py::test_valid[empty]'` | That one case                        |

Paths are relative to the directory you run from. Quote a target that names a case, since the shell reads `[` and spaces itself. The [re-run command](#failures) a failure prints is already quoted.

`-k` matches against the whole id, which starts with the file's path. So `-k checkout` keeps every test in `tests/checkout/` as well as any test with "checkout" in its name.

Targets, `-k` and the tag flags combine: a test runs when it's inside a target and passes every filter.

### Exit codes

| Code | Meaning                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------------- |
| `0`  | Every test that ran passed. Skipped tests don't change this                                             |
| `1`  | A test failed, or a file couldn't be collected                                                          |
| `2`  | The run couldn't start: a target doesn't exist, or the [project lifecycle](#project-lifecycle) is wrong |
| `5`  | No tests matched                                                                                        |

### Environment

`plain test` sets `PLAIN_ENV=test` unless you've set it yourself, then loads `.env.test`. With [plain.dev](../../../plain-dev/plain/dev/README.md#env-files) installed you get its whole ladder of `.env` files, where `.env.local` is left out under `PLAIN_ENV=test` so personal credentials don't reach the suite.

It also sets `PLAIN_TEST_RUNNING=1`. Plain's own command output reads that to leave out color codes, so a test asserting on the output of a command sees plain text.

## Where tests live

Put tests in `tests/`, beside `app/`. The runner looks for:

- Files named `test_*.py`, in any subdirectory
- Functions named `test_*`
- Classes named `Test*`, and the `test_*` methods on them
- `async def test_*`, which the runner awaits for you

```python
# tests/test_cart.py
from plain.test import Client


def test_empty_cart():
    assert Client().get("/cart/").status_code == 200


class TestCheckout:
    def test_requires_login(self):
        assert Client().get("/checkout/").redirect_to == "/login/"


async def test_price_lookup():
    assert await fetch_price("A-1") == 1200
```

A class is a way to group tests, and nothing more. Each test gets a fresh instance, and there are no setup or teardown methods. A class inherits the tests of its base classes.

With no target, `plain test` searches the directory you ran it from. It doesn't look in `app/`, in directories whose name starts with a dot, or in `node_modules`.

### Shared helpers

Shared setup is ordinary Python. Write a module and import it:

```python
# tests/helpers.py
from app.users.models import User


def create_user(*, email="test@example.com"):
    return User.query.create(email=email)
```

```python
# tests/accounts/test_profile.py
from helpers import create_user
from plain.test import Client


def test_profile_shows_the_email():
    user = create_user(email="ada@example.com")
    response = Client().get(f"/users/{user.id}/")
    assert "ada@example.com" in response.text
```

`tests/` is on the import path, so `tests/helpers.py` is `helpers`. That's true for a test file in any subdirectory, whichever directory you run from, and whatever target you pass.

It's the only way to import one. `from tests.helpers import ...` and a relative `from .helpers import ...` are [collection errors](#collection-errors) that say what to write instead. A module imported under two names is loaded twice, and the two copies don't share their state.

`tests/` comes first on the import path, so a helper module named like an installed package takes its place. Give a helper module a name nothing else has.

There are no fixtures and no `conftest.py`: a test gets what it needs by calling for it. A `conftest.py` anywhere under the tests is a collection error.

Only files named `test_*.py` have their [assertions](#assertions) rewritten. An `assert` in a helper module fails as a bare `AssertionError`.

## Reading the output

Each test prints one character as it finishes: `.` passed, `F` failed, `s` skipped. With `-v` each test gets a line of its own:

```
PASSED  tests/test_cart.py::test_empty_cart (0.012s)
SKIPPED tests/test_cart.py::test_refund (Waiting on the new billing API)
```

The last line counts what happened:

```
41 passed, 1 failed, 2 skipped, 1 collection errors in 0.62s
```

Output isn't captured. What a test prints or logs shows up where it happens, between the progress characters.

### Failures

Every failure is listed after the run, and ends with the command that runs that test again:

```
FAILED tests/test_signup.py::test_signup_redirects

  Traceback (most recent call last):
    File "/project/tests/test_signup.py", line 8, in test_signup_redirects
      assert response.status_code == 302
  AssertionError: assert response.status_code == 302
    left:  200
    right: 302

Re-run: plain test tests/test_signup.py::test_signup_redirects
```

The traceback starts at your test. The runner's own frames are left out.

The command is quoted wherever a shell would read the id for itself, so you can paste it as it is:

```
Re-run: plain test 'tests/test_price.py::test_total[annual plan]'
```

### Skipped tests

A skipped test is listed with its reason, whether it came from `@skip` or from [`skip_test`](../../../plain/plain/test/README.md#skipping-from-inside-a-test), and it's counted in the summary:

```
SKIPPED tests/test_uploads.py::test_upload_to_bucket (No bucket reachable from this machine)
```

### Collection errors

A file that can't be turned into tests is a collection error. The other files still run, and the run exits `1`.

```
COLLECTION ERROR /project/tests/test_signup.py

  TestDefinitionError: These tests can't be run as written:

    test_signup(db, client) takes parameters, and nothing passes them in.

  There are no fixtures: nothing is passed to a test by name. A test gets
  what it needs in its body, by calling a helper or entering a `with`
  block, and takes values only from @cases(...).
```

Every test in the file with a problem is named at once. Here is what each message is asking for:

| Message                                                            | What to do                                                                                              |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `test_x(db, client) takes parameters, and nothing passes them in.` | Remove the parameters. Build what the test needs in its body, or pass values with `@cases`              |
| `test_x(a, b) doesn't fit its @cases: case [0] passes 1 value.`    | Make that case pass as many values as the test has parameters                                           |
| `TestCart::test_add() is a method, and has no self parameter.`     | Add `self`                                                                                              |
| `TypeError: test_x already has @cases.`                            | Use one `@cases`. For every combination of two lists, write `@cases(*itertools.product(FIRST, SECOND))` |
| `TypeError: @skip requires a reason`                               | Write `@skip("why")`, not a bare `@skip`                                                                |
| `TypeError: @tag requires at least one name`                       | Write `@tag("slow")`, not a bare `@tag`                                                                 |
| `from tests.helpers import x should be from helpers import x`      | Write the import the message gives. A [helper module](#shared-helpers) is imported by its bare name     |
| `ConftestNotSupported: conftest.py is a pytest file, ...`          | Move what the file holds, then delete it. See below                                                     |
| Anything else, such as `ModuleNotFoundError: No module named 'x'`  | The file raised while it was being imported. Fix the import or the module-level code                    |

A `conftest.py` is reported for every directory that has one, with the fixtures it defines listed by name:

```
COLLECTION ERROR /project/tests/conftest.py

  ConftestNotSupported: conftest.py is a pytest file, and nothing reads it here. There are no
  fixtures: nothing in this file runs, and nothing is passed to a test
  by name. Move what it holds, then delete the file.

  - A fixture that tests ask for becomes a function in a helper module,
    such as tests/helpers.py. A test imports it
    (`from helpers import create_user`) and calls it in its body. A
    fixture that cleans up after itself becomes a `@contextmanager`
    that the test enters with `with`.
  - A fixture that protected every test without being asked for
    (`autouse=True`) becomes a TestLifecycle's `around_test()`, in
    tests/lifecycle.py.
  - Hooks (`pytest_configure`, `pytest_collection_modifyitems`, ...)
    have no equivalent.

  Fixtures in this file: user, organization

  Autouse fixtures in this file: no_payments
```

The tests that needed nothing from it still run. The ones that asked for a fixture are collection errors of their own.

## Assertions

Use bare `assert`. When a comparison fails, the runner shows the expression as you wrote it, parentheses and line breaks included, and the value on each side:

```
AssertionError: assert response.status_code == 302
  left:  200
  right: 302
```

That works for a single comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`, `is`, `is not`, `in`, `not in`. Any other assertion shows the expression that was false:

```
AssertionError: assert user.is_active and user.is_staff
```

A message you give comes first:

```python
assert items, "expected some items"
```

```
AssertionError: expected some items
assert items
```

Each side is evaluated once, so an assertion with a side effect behaves the same as it would without the runner. Long values are shortened: a string to 400 characters, a list or dict to 20 items.

For an exception you expect, use [`raises`](../../../plain/plain/test/README.md#expected-exceptions) from `plain.test`.

## What packages do for every test

An installed Plain package can wrap every test in protection of its own, with no setup on your part. Two do:

- [plain.postgres](../../../plain-postgres/plain/postgres/README.md#testing) creates a test database for the run, and rolls back everything each test wrote.
- [plain.email](../../../plain-email/plain/email/README.md#testing) collects sent mail in memory, so no test sends a real one, and empties the outbox before each test.

A package's protection applies only when the package is in your app's `INSTALLED_PACKAGES`.

Packages ship their test helpers too, in `plain.<package>.test`, and document them in their own READMEs. The Testing section of a package's README is where to look.

## Project lifecycle

Some things have to be true for every test, and a test that forgets one fails in a way that's hard to see: a request reaches a real payment provider, or a rate limiter still holds the last test's count. That's protection, and it doesn't belong in each test's body. Declare it once, in `tests/lifecycle.py`:

```python
# tests/lifecycle.py
from contextlib import contextmanager

from plain.test import TestLifecycle, override_settings

from app.accounts import throttles


class AppTestLifecycle(TestLifecycle):
    @contextmanager
    def around_test(self, test):
        throttles.reset_all()
        # No test reaches the payment provider, whatever the environment holds.
        with override_settings(PAYMENTS_API_KEY=""):
            yield
```

The runner finds the file by its path. There is nothing to register and no other place it looks.

- **One file, one class.** `tests/lifecycle.py` defines exactly one [`TestLifecycle`](../../../plain/plain/test/README.md#test-lifecycles) subclass, under any name. `around_test(test)` wraps each test, and `setup_worker()` / `teardown_worker()` run once, before the first test and after the last.
- **It fails loudly.** If the file is there and doesn't import, defines no `TestLifecycle` subclass, defines more than one, or defines one that can't be created without arguments, the run stops before any test with a message saying which.
- **It runs closest to the test.** Package lifecycles enter first, in the order of their entry point names, and the project's enters last. So the database transaction is already open when yours starts, and yours exits before the transaction is rolled back.
- **It's for protection, not setup.** A user, an organization, a logged-in client: a test that reads one builds it in its body, by calling a helper. If a test would be wrong without the thing but never mentions it, that's the lifecycle's job.

The file has to be `tests/lifecycle.py`. A lifecycle written somewhere the runner doesn't read would protect nothing, so the places one ends up by mistake are checked: `tests/lifecycles.py`, `tests/life_cycle.py`, `tests/lifecycle/__init__.py`, and `lifecycle.py` or `lifecycles.py` beside `tests/`. If one of those is there and mentions `TestLifecycle`, the run stops and says where the file belongs. A `lifecycle.py` deeper inside `tests/` isn't checked, and isn't loaded.

`tests/lifecycle.py` imports [helper modules](#shared-helpers) the way a test file does, by their bare names.

`tests/` is the directory beside `app/`. If you run `plain test` from inside a directory named `tests`, the file is that directory's `lifecycle.py`.

## Testing code outside the app

`plain test` works in a project with no Plain app at all. The runner notices there's no app and leaves the app out:

- Collection, assertion rewriting, targets and the flags all work.
- So does everything in `plain.test` that doesn't need an app: `raises`, `@cases`, `@skip`, `@tag`, `skip_test`, `patch`.
- [`tests/lifecycle.py`](#project-lifecycle) is still loaded.
- Packages' protection is not. There's no test database and no outbox.
- `Client` and `override_settings` need an app, and fail without one.

There's nothing to configure. Whether there's an app is decided the way every `plain` command decides it.

One run is one app. In a repository with several apps, run `plain test` once in each.

## How it works

Testing is split across three places, and the split is what keeps a dev-only package out of production code.

**`plain.test` ships with Plain.** It's what a test file imports: `Client`, `raises`, the decorators, the `with` helpers, the `TestLifecycle` class, and the `CollectedTest` a lifecycle is handed. None of it needs the runner. It has to live in core because core uses it too: `plain request` is built on `Client`.

**`plain.testing` is this package, a dev dependency.** It's the `plain test` command: finding tests, rewriting assertions, running them and reporting. Nothing imports it, your tests included. It imports you. What it offers is the command and the two ways to extend it below, and none of its modules is an API.

**Each package owns its own testing.** Its helpers are in `plain.<package>.test`, and what it does around every test is a [`TestLifecycle`](../../../plain/plain/test/README.md#test-lifecycles) it registers under the `plain.testing` entry point group:

```toml
# plain-postgres/pyproject.toml
[project.entry-points."plain.testing"]
postgres = "plain.postgres.test.lifecycle:PostgresTestLifecycle"
```

An entry point is a string in `pyproject.toml`, so a package declares its lifecycle without depending on the runner.

The line between the first two: **if a test file imports it, it's in `plain.test`. If it runs test files, it's here.**

There are two ways to extend the runner, and no others: a package's entry point, and your project's [`tests/lifecycle.py`](#project-lifecycle). There are no plugins and no hooks.

```
your tests     ──import──▶  plain.test  +  plain.<package>.test
plain.testing  ──drives──▶  lifecycle entry points  (one per package)
plain.testing  ──drives──▶  tests/lifecycle.py      (your project's)
```

## Design rules

The runner and `plain.test` are built by eight rules. When a question about the API comes up, these settle it.

1. **No backwards compatibility.** There is one spelling of each thing, and no alias kept for an old one. `/plain-upgrade` rewrites what changes.
2. **Explicit over implicit.** Everything a test depends on is visible in its own file, as an import, a call, or a `with` block. Decorators declare, bodies acquire: a decorator attaches a static fact (its cases, its tags), and runtime state always enters in the body, where its scope is indentation.
3. **One name per thing.** If two spellings do the same job, one goes. The bytes a response sent are `body`, and nothing else.
4. **Fail early, and say what to do.** A mistake is rejected when the file is collected, with a message naming the fix. Nothing is silently overwritten or ignored: a test that asks for parameters nothing passes in, a second `@cases`, a bare `@skip`.
5. **The report tells the truth.** A test that didn't run is reported as skipped, with its reason. Nothing disappears from the count.
6. **Repetition earns a helper, never magic.** When the same lines appear in many tests, the answer is a named function or context manager the tests call. It is never injection.
7. **Standard library first, and helpers live with their owner.** The runner doesn't wrap what Python already does well (`tempfile.TemporaryDirectory`, `math.isclose`, `contextlib.redirect_stdout`). A helper specific to a package ships in that package's `plain.<package>.test`.
8. **Setup is explicit, protection is automatic.** State a test reads is acquired in its body. What guards tests from each other and from the outside world belongs in a lifecycle, which wraps every test without being asked. Packages ship theirs; your project declares its own in [one place](#project-lifecycle).

## FAQs

#### Why is the package named `plain.testing` when I import from `plain.test`?

They're different things with different install lives. `plain.test` is part of Plain and has to stay there, because Plain uses it at runtime (`plain request` makes its requests with `Client`). A dev-only package can't own a module that production code imports. So you **install** `plain.testing`, you **import** from `plain.test`, and you **run** `plain test`.

#### How do I debug a failing test?

Put `breakpoint()` where you want to stop and run the test. The runner doesn't capture output or input, so the debugger prompt works the way it does in any script. Every failure prints the command that runs it again, so you can copy that to run the one test.

#### Does coverage work?

Yes. `python -m plain.testing` is the same runner as `plain test`, so `coverage run -m plain.testing` works with no plugin.

#### Can I use pytest, or pytest plugins?

No. This isn't pytest, and there's nothing to load a plugin into. A library that doesn't depend on pytest keeps working as a library: `freezegun` and `time-machine` for freezing time, `hypothesis` for generated inputs, `unittest.mock` for mocks.

#### What about my editor's test explorer?

Editors speak pytest's protocol, which this runner doesn't. Run tests from the terminal. Every failure prints the command that runs it again.

#### Why aren't there fixtures?

A fixture hands a test something by the name of its parameter, from a file the test doesn't mention. Here the same needs are met two other ways. Protection every test needs comes from a lifecycle: the database and the outbox from packages, your own from [`tests/lifecycle.py`](#project-lifecycle). Everything else is a function or a context manager the test imports and calls.

#### What replaces an autouse fixture?

It depends on what the fixture was for. If it protected every test (no network, counters reset), it becomes the [project lifecycle](#project-lifecycle). If it set something up for the tests in one file, it becomes a context manager those tests enter with `with`. That repeats a line in each test, and it's the line that says what the test depends on.

#### What replaces `tmp_path`, `capsys` and `approx`?

The standard library. `tempfile.TemporaryDirectory()` for a directory that's removed afterwards, `contextlib.redirect_stdout(io.StringIO())` to read what was printed, and `math.isclose(a, b, abs_tol=...)` inside a bare `assert`.

## Installation

Install the `plain.testing` package from [PyPI](https://pypi.org/project/plain.testing/) as a dev dependency:

```bash
uv add plain.testing --dev
```

Then run your tests:

```bash
plain test
```

There's no configuration file. `.env.test` is loaded, installed packages add their protection, and `tests/lifecycle.py` adds yours.
