# plain-flags changelog

## [0.27.3](https://github.com/dropseed/plain/releases/plain-flags@0.27.3) (2025-11-11)

### What's changed

- Internal import path updated for database exceptions to use `plain.models.db` ([e9edf61](https://github.com/dropseed/plain/commit/e9edf61c6b))

### Upgrade instructions

- No changes required

## [0.27.2](https://github.com/dropseed/plain/releases/plain-flags@0.27.2) (2025-10-31)

### What's changed

- Package metadata now includes explicit BSD-3-Clause license field ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.27.1](https://github.com/dropseed/plain/releases/plain-flags@0.27.1) (2025-10-20)

### What's changed

- Build configuration updated to use standardized `[dependency-groups]` instead of `[tool.uv]` for dev dependencies ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.27.0](https://github.com/dropseed/plain/releases/plain-flags@0.27.0) (2025-10-12)

### What's changed

- The unused flags preflight check has been refactored from a model method into an independent `PreflightCheck` class registered with `@register_check` ([38b43f3](https://github.com/dropseed/plain/commit/38b43f3))

### Upgrade instructions

- No changes required

## [0.26.0](https://github.com/dropseed/plain/releases/plain-flags@0.26.0) (2025-10-07)

### What's changed

- Model definitions now use `model_options = models.Options()` instead of `class Meta:` ([17a378d](https://github.com/dropseed/plain/commit/17a378d), [73ba469](https://github.com/dropseed/plain/commit/73ba469))
- Internal model metadata access updated to use `model_options` and `_model_meta` properties ([73ba469](https://github.com/dropseed/plain/commit/73ba469))

### Upgrade instructions

- No changes required

## [0.25.3](https://github.com/dropseed/plain/releases/plain-flags@0.25.3) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package to improve IDE and type checker support ([f05463f](https://github.com/dropseed/plain/commit/f05463f285))

### Upgrade instructions

- No changes required

## [0.25.2](https://github.com/dropseed/plain/releases/plain-flags@0.25.2) (2025-10-02)

### What's changed

- Updated README documentation to use `get_current_user()` instead of `request.user` in template examples ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.25.1](https://github.com/dropseed/plain/releases/plain-flags@0.25.1) (2025-09-29)

### What's changed

- Fixed the admin interface for unused flags to display the `fix` field instead of `message` field in PreflightResult ([b75a38d](https://github.com/dropseed/plain/commit/b75a38d52a))

### Upgrade instructions

- No changes required

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
