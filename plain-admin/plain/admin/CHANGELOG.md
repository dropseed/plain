# plain-admin changelog

## [0.33.0](https://github.com/dropseed/plain/releases/plain-admin@0.33.0) (2025-06-23)

### What's changed

- The QueryStats browser toolbar now logs a concise summary message in the developer console instead of the full `PerformanceEntry` object, making query-timing information easier to scan ([fcd92a6](https://github.com/dropseed/plain/commit/fcd92a6)).
- QueryStats middleware now uses `plain.models.db_connection`, aligning with the new single-`DATABASE` configuration and removing the dependency on `DEFAULT_DB_ALIAS` ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).

### Upgrade instructions

- No changes required

