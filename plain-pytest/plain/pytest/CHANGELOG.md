# plain-pytest changelog

## [0.16.2](https://github.com/dropseed/plain/releases/plain-pytest@0.16.2) (2026-02-04)

### What's changed

- Moved `.env.test` loading from the CLI command to the pytest plugin, ensuring environment variables are loaded even when running pytest directly without the `plain test` wrapper ([9c7100bd4ec9](https://github.com/dropseed/plain/commit/9c7100bd4ec9))
- The CLI now uses `os.execvp()` to replace the process with pytest instead of spawning a subprocess, improving signal handling and process management ([9c7100bd4ec9](https://github.com/dropseed/plain/commit/9c7100bd4ec9))

### Upgrade instructions

- No changes required.

## [0.16.1](https://github.com/dropseed/plain/releases/plain-pytest@0.16.1) (2026-01-28)

### What's changed

- Converted the `plain-test` skill to a passive `.claude/rules/` file ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))

### Upgrade instructions

- Run `plain agent install` to update your `.claude/` directory.

## [0.16.0](https://github.com/dropseed/plain/releases/plain-pytest@0.16.0) (2026-01-15)

### What's changed

- Replaced `python-dotenv` dependency with Plain's built-in dotenv parser, which supports bash-compatible features like variable expansion, command substitution, and backslash escapes ([a9b2dc3e](https://github.com/dropseed/plain/commit/a9b2dc3e))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-pytest@0.15.0) (2026-01-13)

### What's changed

- Expanded README documentation with more examples and a FAQs section ([da37a78f](https://github.com/dropseed/plain/commit/da37a78f))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-pytest@0.14.0) (2026-01-13)

### What's changed

- Added a `plain-test` skill to help AI coding assistants run and understand tests ([b592c32c](https://github.com/dropseed/plain/commit/b592c32c))

### Upgrade instructions

- No changes required

## [0.13.2](https://github.com/dropseed/plain/releases/plain-pytest@0.13.2) (2025-11-17)

### What's changed

- No functional code changes. This release only updates internal tooling and documentation.

### Upgrade instructions

- No changes required

## [0.13.1](https://github.com/dropseed/plain/releases/plain-pytest@0.13.1) (2025-11-03)

### What's changed

- The `plain test` command is now marked as a "common command" to show it in the default CLI help output ([73d3a48f](https://github.com/dropseed/plain/commit/73d3a48f))
- Updated the `plain test` command description to "Test suite with pytest" for clarity ([fdb9e801](https://github.com/dropseed/plain/commit/fdb9e801))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-pytest@0.13.0) (2025-10-17)

### What's changed

- The `testbrowser` now uses `plain server` instead of `gunicorn` to run the test server process ([51461b99](https://github.com/dropseed/plain/commit/51461b99))

### Upgrade instructions

- Remove `gunicorn` from your project dependencies if it was only being used for the `testbrowser` fixture

## [0.12.2](https://github.com/dropseed/plain/releases/plain-pytest@0.12.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations to all public methods and functions ([c87ca27e](https://github.com/dropseed/plain/commit/c87ca27e))

### Upgrade instructions

- No changes required

## [0.12.1](https://github.com/dropseed/plain/releases/plain-pytest@0.12.1) (2025-09-25)

### What's changed

- The CLI output when loading `.env.test` is now dimmed and italicized for a cleaner test output ([6166ab78](https://github.com/dropseed/plain/commit/6166ab78))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-pytest@0.12.0) (2025-09-22)

### What's changed

- Removed automatic addition of "testserver" to `ALLOWED_HOSTS` during pytest runs, as Plain now defaults `ALLOWED_HOSTS` to an empty list with better host validation ([d3cb7712](https://github.com/dropseed/plain/commit/d3cb7712))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-pytest@0.11.0) (2025-09-19)

### What's changed

- Minimum Python version increased to 3.13 ([d86e307e](https://github.com/dropseed/plain/commit/d86e307e))
- Color output is now properly disabled during pytest runs to prevent formatting issues ([88f1bac6](https://github.com/dropseed/plain/commit/88f1bac6))

### Upgrade instructions

- Upgrade your Python environment to 3.13 or later

## [0.10.1](https://github.com/dropseed/plain/releases/plain-pytest@0.10.1) (2025-07-30)

### What's changed

- `TestBrowser.discover_urls` now handles query-parameter-only URLs (e.g., "?stage=approved") by resolving them relative to the current page path ([4651a7b](https://github.com/dropseed/plain/commit/4651a7b))

### Upgrade instructions

- No changes required

## [0.10.0](https://github.com/dropseed/plain/releases/plain-pytest@0.10.0) (2025-06-27)

### What's changed

- `TestBrowser.discover_urls` now accepts _one_ argument: a list of URL strings. Previously it accepted a variable number of positional arguments. This provides clearer typing and usage ([3d56b1f](https://github.com/dropseed/plain/commit/3d56b1f)).

### Upgrade instructions

- Wrap the URLs you pass to `testbrowser.discover_urls` in a list. For example, change `testbrowser.discover_urls("/", "/about/")` to `testbrowser.discover_urls(["/", "/about/"])`.

## [0.9.1](https://github.com/dropseed/plain/releases/plain-pytest@0.9.1) (2025-06-26)

### What's changed

- No functional code changes. This release only updates internal tooling and documentation.

### Upgrade instructions

- No changes required.

## [0.9.0](https://github.com/dropseed/plain/releases/plain-pytest@0.9.0) (2025-06-23)

### What's changed

- `testbrowser` fixture now derives the database URL from `plain.models.db_connection`, aligning with Plain's new single `DATABASE` setting and removing the dependency on `DEFAULT_DB_ALIAS`/`connections` ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).

### Upgrade instructions

- Upgrade your project to `plain>=0.50.0` (which introduces the single `DATABASE` setting). No other changes required.
