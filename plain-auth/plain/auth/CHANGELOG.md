# plain-auth changelog

## [0.17.0](https://github.com/dropseed/plain/releases/plain-auth@0.17.0) (2025-09-12)

### What's changed

- Model managers are now accessed via `.query` instead of `.objects` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Updated to require Python 3.13 minimum ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Replace any usage of `Model.objects` with `Model.query` in your code (e.g., `User.objects.get()` becomes `User.query.get()`)

## [0.16.0](https://github.com/dropseed/plain/releases/plain-auth@0.16.0) (2025-08-19)

### What's changed

- Removed automatic CSRF token rotation on login as part of CSRF system refactor using Sec-Fetch-Site headers ([9551508](https://github.com/dropseed/plain/commit/955150800c))
- Updated README with improved documentation, examples, and better package description ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

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
