# plain-auth changelog

## [0.20.1](https://github.com/dropseed/plain/releases/plain-auth@0.20.1) (2025-10-02)

### What's changed

- Updated README documentation to use `get_request_user()` and `get_current_user()` instead of `request.user` ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.20.0](https://github.com/dropseed/plain/releases/plain-auth@0.20.0) (2025-10-02)

### What's changed

- Removed `AuthenticationMiddleware` - authentication is now handled through request-based functions instead of middleware ([154ee10](https://github.com/dropseed/plain/commit/154ee10))
- Replaced `request.user` attribute with `get_request_user(request)` function and `{{ get_current_user() }}` template global ([154ee10](https://github.com/dropseed/plain/commit/154ee10))
- `AuthViewMixin` now provides a `self.user` property for accessing the authenticated user in views ([154ee10](https://github.com/dropseed/plain/commit/154ee10))
- Renamed `get_user` to `get_request_user` in the public API ([154ee10](https://github.com/dropseed/plain/commit/154ee10))

### Upgrade instructions

- Remove `plain.auth.middleware.AuthenticationMiddleware` from your `MIDDLEWARE` setting
- In views, use `AuthViewMixin` for access to `self.user` instead of `self.request.user`
- Replace `request.user` with `get_request_user(request)` in code outside of `AuthViewMixin` views
- In templates, replace `{{ request.user }}` with `{{ user }}` (from `AuthViewMixin`) or with `{{ get_current_user() }}`

## [0.19.0](https://github.com/dropseed/plain/releases/plain-auth@0.19.0) (2025-09-30)

### What's changed

- Updated imports to use the renamed `Request` class instead of `HttpRequest` ([cd46ff2](https://github.com/dropseed/plain/commit/cd46ff2003))

### Upgrade instructions

- Replace any imports of `HttpRequest` from `plain.http.request` with `Request` (e.g., `from plain.http.request import HttpRequest` becomes `from plain.http.request import Request`)

## [0.18.0](https://github.com/dropseed/plain/releases/plain-auth@0.18.0) (2025-09-19)

### What's changed

- Removed deprecated `constant_time_compare` utility function, replaced with Python's built-in `hmac.compare_digest()` for improved security in session management ([55f3f55](https://github.com/dropseed/plain/commit/55f3f5596d))

### Upgrade instructions

- No changes required

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
