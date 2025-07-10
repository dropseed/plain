# plain-admin changelog

## [0.33.2](https://github.com/dropseed/plain/releases/plain-admin@0.33.2) (2025-07-07)

### What's changed

- No user-facing changes in this release. Internal CSS cleanup and linter adjustments were made to the bundled admin styles ([3265f5f](https://github.com/dropseed/plain/commit/3265f5f)).

### Upgrade instructions

- No changes required

## [0.33.1](https://github.com/dropseed/plain/releases/plain-admin@0.33.1) (2025-06-26)

### What's changed

- No user-facing changes in this release. Internal documentation formatting was improved ([2fc81de](https://github.com/dropseed/plain/commit/2fc81de)).

### Upgrade instructions

- No changes required

## [0.33.0](https://github.com/dropseed/plain/releases/plain-admin@0.33.0) (2025-06-23)

### What's changed

- The QueryStats browser toolbar now logs a concise summary message in the developer console instead of the full `PerformanceEntry` object, making query-timing information easier to scan ([fcd92a6](https://github.com/dropseed/plain/commit/fcd92a6)).
- QueryStats middleware now uses `plain.models.db_connection`, aligning with the new single-`DATABASE` configuration and removing the dependency on `DEFAULT_DB_ALIAS` ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).

### Upgrade instructions

- No changes required
