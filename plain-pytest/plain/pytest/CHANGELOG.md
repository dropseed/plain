# plain-pytest changelog

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
