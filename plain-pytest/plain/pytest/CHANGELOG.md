# plain-pytest changelog

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
