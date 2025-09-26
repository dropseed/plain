# plain-flags changelog

## [0.25.0](https://github.com/dropseed/plain/releases/plain-flags@0.25.0) (2025-09-26)

### What's changed

- Removed unused `uuid` fields from `Flag` and `FlagResult` models along with their associated unique constraints ([331ce37](https://github.com/dropseed/plain/commit/331ce37992))

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-flags@0.24.0) (2025-09-25)

### What's changed

- The `Flag.check()` method has been renamed to `Flag.preflight()` to align with the new preflight system ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))
- Preflight results now use the new `PreflightResult` class instead of `Info` ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))
- Database connection errors are now handled more gracefully during preflight checks by catching both `ProgrammingError` and `OperationalError` ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))
- Preflight result messages and hints have been unified into a single `fix` field ([c7cde12](https://github.com/dropseed/plain/commit/c7cde12149))

### Upgrade instructions

- No changes required

## [0.23.0](https://github.com/dropseed/plain/releases/plain-flags@0.23.0) (2025-09-12)

### What's changed

- Updated model API to use `.query` instead of `.objects` for database operations ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version requirement increased to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Admin navigation icon updated from "flag-fill" to "flag" ([2aac07d](https://github.com/dropseed/plain/commit/2aac07de4e))

### Upgrade instructions

- No changes required (the `.objects` to `.query` change is handled internally by the framework)

## [0.22.0](https://github.com/dropseed/plain/releases/plain-flags@0.22.0) (2025-08-19)

### What's changed

- Removed manual CSRF token from admin flag result form template, now handled automatically by Sec-Fetch-Site headers ([9551508](https://github.com/dropseed/plain/commit/955150800c))
- Updated README with better structure, table of contents, and improved installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.21.1](https://github.com/dropseed/plain/releases/plain-flags@0.21.1) (2025-07-23)

### What's changed

- Admin navigation now includes Bootstrap icons for Flag and FlagResult sections ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0e2c))

### Upgrade instructions

- No changes required

## [0.21.0](https://github.com/dropseed/plain/releases/plain-flags@0.21.0) (2025-07-22)

### What's changed

- Updated model migrations to use `PrimaryKeyField()` instead of `BigAutoField(auto_created=True, primary_key=True)` ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))
- Model key coercion now uses `id` instead of deprecated `pk` alias when generating flag keys ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))

### Upgrade instructions

- No changes required

## [0.20.0](https://github.com/dropseed/plain/releases/plain-flags@0.20.0) (2025-07-18)

### What's changed

- Added OpenTelemetry tracing support to flag evaluation with detailed spans and attributes ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))

### Upgrade instructions

- No changes required

## [0.19.0](https://github.com/dropseed/plain/releases/plain-flags@0.19.0) (2025-07-18)

### What's changed

- Migrations have been restarted and consolidated into a single initial migration ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainflags` to clean up old migrations when upgrading from a previous version

## [0.18.0](https://github.com/dropseed/plain/releases/plain-flags@0.18.0) (2025-06-23)

### What's changed

- Dropped multi-database support: `Flag.check()` now follows updated standard system-check signature that receives a single `database` keyword argument instead of `databases`. Internally the check no longer loops over multiple connections (d346d81).
- Updated the admin “Unused flags” card to use the new `database` keyword (d346d81).

### Upgrade instructions

- No changes required.
