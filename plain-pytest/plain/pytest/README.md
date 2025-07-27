# plain.pytest

**Test with pytest.**

- [Overview](#overview)
- [Fixtures](#fixtures)
    - [`settings`](#settings)
    - [`testbrowser`](#testbrowser)
- [Installation](#installation)

## Overview

Use the `plain test` command to run tests with pytest and automatically load a `.env.test` (if available).

```python
def test_example(settings):
    settings.DEBUG = True
    assert settings.DEBUG is True
```

## Fixtures

### `settings`

Use the [`settings`](./plugin.py#settings) fixture to access and modify settings during tests. Any changes made to settings are automatically restored after the test completes.

```python
def test_example(settings):
    settings.DEBUG = True
    assert settings.DEBUG is True
```

### `testbrowser`

A lightweight wrapper around [Playwright](https://playwright.dev/python/) that starts a gunicorn side-process to point the browser at. The [`testbrowser`](./plugin.py#testbrowser) fixture provides access to a [`TestBrowser`](./browser.py#TestBrowser) instance.

Note that `playwright`, `pytest-playwright`, and `gunicorn` are not dependencies of this package but are required if you want to use this fixture.

```python
def test_example(testbrowser):
    page = testbrowser.new_page()
    page.goto('/')
    assert page.title() == 'Home Page'
```

The `testbrowser` includes useful methods:

- [`force_login(user)`](./browser.py#force_login) - Log in a user without going through the login flow
- [`logout()`](./browser.py#logout) - Clear all cookies to log out
- [`discover_urls(urls)`](./browser.py#discover_urls) - Recursively discover all URLs starting from the given URLs

If `plain.models` is installed, then the `testbrowser` will also load the [`isolated_db`](/plain-models/plain/models/test/pytest.py#isolated_db) fixture and pass a `DATABASE_URL` to the gunicorn process.

## Installation

Install the `plain.pytest` package from [PyPI](https://pypi.org/project/plain.pytest/):

```bash
uv add plain.pytest --dev
```
