# plain-pytest changelog

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
