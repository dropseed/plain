# plain-flags changelog

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
