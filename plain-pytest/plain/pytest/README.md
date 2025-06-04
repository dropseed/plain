# plain.pytest

**Test with pytest.**

Use the `plain test` command to run tests with pytest and automatically load a `.env.test` (if available).

## Fixtures

### `settings`

Use the `settings` fixture to access and modify settings during tests.

```python
def test_example(settings):
    settings.DEBUG = True
    assert settings.DEBUG is True
```

### `testbrowser`

A lightweight wrapper around playwright that starts a gunicorn side-process to point the browser at.

Note that `playwright`, `pytest-playwright`, and `gunicorn` are not dependencies of this package but are required if you want to use this fixture.

```python
def test_example(testbrowser):
    page = testbrowser.new_page()
    page.goto('/')
    assert page.title() == 'Home Page'
```
