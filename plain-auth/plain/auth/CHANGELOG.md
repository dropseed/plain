# plain-auth changelog

## [0.15.0](https://github.com/dropseed/plain/releases/plain-auth@0.15.0) (2025-07-22)

### What's changed

- Replaced `pk` field references with `id` field references in session management ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))
- Simplified user ID handling in sessions by using direct integer storage instead of field serialization ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-auth@0.14.0) (2025-07-18)

### What's changed

- Added OpenTelemetry tracing support with automatic user ID attribute setting in auth middleware ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-auth@0.13.0) (2025-06-23)

### What's changed

- Added `login_client` and `logout_client` helpers to `plain.auth.test` for easily logging users in and out of the Django test client ([eb8a023](https://github.com/dropseed/plain/commit/eb8a023)).

### Upgrade instructions

- No changes required
