# plain-auth changelog

## [0.29.4](https://github.com/dropseed/plain/releases/plain-auth@0.29.4) (2026-04-23)

### What's changed

- `AuthView.handle_exception` and `AuthView.after_response` annotate against `Response` after plain 0.135.0 merged `ResponseBase` into `Response`. ([f5007281d7fa](https://github.com/dropseed/plain/commit/f5007281d7fa))

### Upgrade instructions

- Requires `plain>=0.135.0`.

## [0.29.3](https://github.com/dropseed/plain/releases/plain-auth@0.29.3) (2026-04-21)

### What's changed

- **Migrated `AuthView` to the new `View` lifecycle hooks.** `check_auth()` runs in `before_request`, the login-redirect logic runs in `handle_exception` (triggered when `check_auth` raises `LoginRequired`), and the `Cache-Control: private` header is set in `after_response`. Behavior is unchanged for users. ([48effac976a9](https://github.com/dropseed/plain/commit/48effac976a9), [a4a88ed08cb9](https://github.com/dropseed/plain/commit/a4a88ed08cb9), [0da5639d17e2](https://github.com/dropseed/plain/commit/0da5639d17e2))
- **`LoginRequired` now subclasses `plain.http.HTTPException`** with `status_code = 401`. Generic handlers (logging, APIs) treat it as a 401 by default; `AuthView.handle_exception` still renders the login redirect for HTML views. The constructor no longer defaults `login_url` to `settings.AUTH_LOGIN_URL` — callers resolve it explicitly (pass `None` to render as 403). ([a4a88ed08cb9](https://github.com/dropseed/plain/commit/a4a88ed08cb9))

### Upgrade instructions

- Requires `plain>=0.133.0`.
- **If you raise `LoginRequired()` directly** with no arguments, pass the login URL explicitly: `LoginRequired(settings.AUTH_LOGIN_URL)`. Passing `None` keeps the old "no login page → 403" behavior.

## [0.29.2](https://github.com/dropseed/plain/releases/plain-auth@0.29.2) (2026-04-17)

### What's changed

- Updated README example to use `DateTimeField(create_now=True)` for plain-postgres 0.96.0. ([5d145e4](https://github.com/dropseed/plain/commit/5d145e4))
- Raised `plain-postgres` floor to `>=0.96.0`.

### Upgrade instructions

- Requires `plain-postgres>=0.96.0`. See the plain-postgres 0.96.0 notes for field-API migration guidance.

## [0.29.1](https://github.com/dropseed/plain/releases/plain-auth@0.29.1) (2026-04-13)

### What's changed

- Switched OTel user attribution from the deprecated `enduser.id` attribute to `user.id`, following the updated OpenTelemetry semantic conventions. ([e02ef5a46213](https://github.com/dropseed/plain/commit/e02ef5a46213))

### Upgrade instructions

- If your tracing/observability tooling queries spans by the `enduser.id` attribute, update it to `user.id`.

## [0.29.0](https://github.com/dropseed/plain/releases/plain-auth@0.29.0) (2026-04-13)

### What's changed

- **Added `AuthMiddleware`** that eagerly resolves `request.user` on every request and stamps the `enduser.id` OTel attribute on the request span. This gives consistent user attribution in traces regardless of whether the view touches `request.user`. Opt-in via `MIDDLEWARE` (after `SessionMiddleware`). ([fe5e3cf8b74a](https://github.com/dropseed/plain/commit/fe5e3cf8b74a))
- **Stamp `enduser.id` whenever a user is resolved or set** via `get_request_user()` / `set_request_user()` / `login()`. The attribute uses the OTel semantic convention (incubating) and only fires when there's a recording span. ([fe5e3cf8b74a](https://github.com/dropseed/plain/commit/fe5e3cf8b74a))
- **Removed `AUTH_USER_MODEL` setting and `get_user_model()` function.** The User class is now fixed at `app.users.models.User` — a required convention, not a configurable setting. ([0861c9915cb6](https://github.com/dropseed/plain/commit/0861c9915cb6))
- Updated type annotations throughout to reference the concrete `User` class instead of the generic `Model`. ([0861c9915cb6](https://github.com/dropseed/plain/commit/0861c9915cb6))
- Migrated type suppression comments to `ty: ignore` and upgraded the ty checker to 0.0.29. ([4ec631a7ef51](https://github.com/dropseed/plain/commit/4ec631a7ef51))

### Upgrade instructions

- Remove `AUTH_USER_MODEL` from `settings.py`. Move your User model to `app/users/models.py` (package label `users`, class name `User`) if it isn't there.
- Replace `from plain.auth import get_user_model; User = get_user_model()` with `from app.users.models import User`.
- To get consistent `enduser.id` attribution on traces, add `"plain.auth.middleware.AuthMiddleware"` to `MIDDLEWARE` after `SessionMiddleware`.

## [0.28.0](https://github.com/dropseed/plain/releases/plain-auth@0.28.0) (2026-03-12)

### What's changed

- Updated all imports from `plain.models` to `plain.postgres` in requests, sessions, views, and README examples.
- Updated `pyproject.toml` dependency from `plain.models` to `plain.postgres`.

### Upgrade instructions

- Update imports: `from plain.models` to `from plain.postgres`, `from plain import models` to `from plain import postgres`.
- Update dependency declarations: `plain.models` to `plain.postgres` in `pyproject.toml`.

## [0.27.3](https://github.com/dropseed/plain/releases/plain-auth@0.27.3) (2026-03-11)

### What's changed

- Added `allow_external=True` to `redirect_to_login` to support SSO configurations where `AUTH_LOGIN_URL` resolves to an external URL ([5edfb2bedf90](https://github.com/dropseed/plain/commit/5edfb2bedf90))

### Upgrade instructions

- Requires `plain>=0.123.0`. No other changes required.

## [0.27.2](https://github.com/dropseed/plain/releases/plain-auth@0.27.2) (2026-03-10)

### What's changed

- Typed user parameters as `Model | None` instead of `Any | None` across `get_request_user()`, `set_request_user()`, auth session functions, and `AuthView.user` ([8b2f42444f01](https://github.com/dropseed/plain/commit/8b2f42444f01))
- Adopted PEP 695 type parameter syntax ([aa5b2db6e8ed](https://github.com/dropseed/plain/commit/aa5b2db6e8ed))

### Upgrade instructions

- No changes required.

## [0.27.1](https://github.com/dropseed/plain/releases/plain-auth@0.27.1) (2026-03-10)

### What's changed

- Updated README code examples to use typed fields (`types.EmailField`, `types.BooleanField`, `types.DateTimeField` with type annotations) ([772345d4e1f1](https://github.com/dropseed/plain/commit/772345d4e1f1))

### Upgrade instructions

- No changes required.

## [0.27.0](https://github.com/dropseed/plain/releases/plain-auth@0.27.0) (2026-03-07)

### What's changed

- Removed positional `*args` from `resolve_url()`, which now only accepts keyword arguments for URL resolution ([6eecc35](https://github.com/dropseed/plain/commit/6eecc35ff197))

### Upgrade instructions

- If you call `resolve_url()` with positional arguments for URL parameters, switch to keyword arguments (e.g., `resolve_url("myapp:detail", obj.pk)` becomes `resolve_url("myapp:detail", pk=obj.pk)`).

## [0.26.1](https://github.com/dropseed/plain/releases/plain-auth@0.26.1) (2026-03-04)

### What's changed

- Added minimum `plain>=0.113.0` version constraint in dependencies ([217751b866](https://github.com/dropseed/plain/commit/217751b866))

### Upgrade instructions

- No changes required.

## [0.26.0](https://github.com/dropseed/plain/releases/plain-auth@0.26.0) (2026-03-04)

### What's changed

- Updated test helpers (`login_client`, `logout_client`) to pass required `method` and `path` arguments when constructing `Request` objects, matching the new `Request.__init__` signature in plain 0.113.0 ([f25f430f54b4](https://github.com/dropseed/plain/commit/f25f430f54b4))

### Upgrade instructions

- Requires plain >= 0.113.0.

## [0.25.4](https://github.com/dropseed/plain/releases/plain-auth@0.25.4) (2026-02-26)

### What's changed

- Auto-formatted config files with updated linter configuration ([028bb95c3ae3](https://github.com/dropseed/plain/commit/028bb95c3ae3))

### Upgrade instructions

- No changes required.

## [0.25.3](https://github.com/dropseed/plain/releases/plain-auth@0.25.3) (2026-02-12)

### What's changed

- Updated README User model example to include `@models.register_model` decorator ([9db8e0aa5d43](https://github.com/dropseed/plain/commit/9db8e0aa5d43))

### Upgrade instructions

- No changes required.

## [0.25.2](https://github.com/dropseed/plain/releases/plain-auth@0.25.2) (2026-02-04)

### What's changed

- Added `__all__` exports to `views` module for explicit public API boundaries ([f26a63a5c941](https://github.com/dropseed/plain/commit/f26a63a5c941))

### Upgrade instructions

- No changes required.

## [0.25.1](https://github.com/dropseed/plain/releases/plain-auth@0.25.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.25.0](https://github.com/dropseed/plain/releases/plain-auth@0.25.0) (2026-01-13)

### What's changed

- Improved README documentation with better examples and consistent structure ([da37a78](https://github.com/dropseed/plain/commit/da37a78fbb))

### Upgrade instructions

- No changes required

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
