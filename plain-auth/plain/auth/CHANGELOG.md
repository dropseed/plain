# plain-auth changelog

## [0.24.0](https://github.com/dropseed/plain/releases/plain-auth@0.24.0) (2026-01-13)

### What's changed

- HTTP exceptions moved from `plain.exceptions` to `plain.http.exceptions` (exported via `plain.http`) ([b61f909](https://github.com/dropseed/plain/commit/b61f909e29))

### Upgrade instructions

- Update imports of HTTP exceptions from `plain.exceptions` to `plain.http` (e.g., `from plain.exceptions import ForbiddenError403` becomes `from plain.http import ForbiddenError403`)

## [0.23.0](https://github.com/dropseed/plain/releases/plain-auth@0.23.0) (2026-01-13)

### What's changed

- HTTP exception classes renamed to include `Error` suffix and status code: `PermissionDenied` → `ForbiddenError403`, `Http404` → `NotFoundError404` ([5a1f020](https://github.com/dropseed/plain/commit/5a1f020f52))
- Response classes renamed: `ResponseRedirect` → `RedirectResponse` ([fad5bf2](https://github.com/dropseed/plain/commit/fad5bf28b0))

### Upgrade instructions

- Replace `PermissionDenied` with `ForbiddenError403` in any custom auth logic (e.g., `raise PermissionDenied("message")` becomes `raise ForbiddenError403("message")`)
- Replace `Http404` with `NotFoundError404` if used in auth-related code
- Replace `ResponseRedirect` with `RedirectResponse` if imported from `plain.http`

## [0.22.0](https://github.com/dropseed/plain/releases/plain-auth@0.22.0) (2025-11-24)

### What's changed

- Replaced `AuthViewMixin` with `AuthView` class that inherits from `SessionView` for better typing and simpler view inheritance ([569afd6](https://github.com/dropseed/plain/commit/569afd606d))

### Upgrade instructions

- Replace `class MyView(AuthViewMixin, View)` with `class MyView(AuthView)` - the new `AuthView` class already inherits from the appropriate base classes

## [0.21.0](https://github.com/dropseed/plain/releases/plain-auth@0.21.0) (2025-11-12)

### What's changed

- Improved type checking compatibility by adding type ignore comment for mixin method resolution in `AuthViewMixin` ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa92))

### Upgrade instructions

- No changes required

## [0.20.7](https://github.com/dropseed/plain/releases/plain-auth@0.20.7) (2025-10-31)

### What's changed

- Added `license = "BSD-3-Clause"` field to `pyproject.toml` for improved package metadata ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.20.6](https://github.com/dropseed/plain/releases/plain-auth@0.20.6) (2025-10-22)

### What's changed

- Fixed impersonation check in `AuthViewMixin` to properly handle optional `plain-admin` dependency using `get_request_impersonator()` function instead of `getattr()` ([548a385](https://github.com/dropseed/plain/commit/548a3859f5))

### Upgrade instructions

- No changes required

## [0.20.5](https://github.com/dropseed/plain/releases/plain-auth@0.20.5) (2025-10-20)

### What's changed

- Updated `pyproject.toml` to use standard `[dependency-groups]` format instead of uv-specific `[tool.uv]` section for development dependencies ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.20.4](https://github.com/dropseed/plain/releases/plain-auth@0.20.4) (2025-10-16)

### What's changed

- The `get_current_user()` template function now catches `SessionNotAvailable` exceptions and returns `None`, preventing errors during error page rendering before middleware runs ([fb889fa](https://github.com/dropseed/plain/commit/fb889fa0e9))

### Upgrade instructions

- No changes required

## [0.20.3](https://github.com/dropseed/plain/releases/plain-auth@0.20.3) (2025-10-07)

### What's changed

- Updated 0.20.0 changelog with additional upgrade instructions about `login_required` default ([221591e](https://github.com/dropseed/plain/commit/221591e48a))

### Upgrade instructions

- No changes required

## [0.20.2](https://github.com/dropseed/plain/releases/plain-auth@0.20.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations across the entire package for improved IDE support and type checking ([786c1db](https://github.com/dropseed/plain/commit/786c1dbdbd))

### Upgrade instructions

- No changes required

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
- The default for `login_required` in `AuthViewMixin` is now `False`, so explicitly set `login_required = True` if needed
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
