# plain-oauth changelog

## [0.32.1](https://github.com/dropseed/plain/releases/plain-oauth@0.32.1) (2025-11-11)

### What's changed

- Internal import paths updated to use more specific module imports (e.g., `plain.models.aggregates.Count` and `plain.models.db.OperationalError`) for better code organization ([e9edf61](https://github.com/dropseed/plain/commit/e9edf61))

### Upgrade instructions

- No changes required

## [0.32.0](https://github.com/dropseed/plain/releases/plain-oauth@0.32.0) (2025-11-03)

### What's changed

- OAuth errors are now logged as warnings instead of exceptions, reducing log noise while still capturing error messages ([30b5705](https://github.com/dropseed/plain/commit/30b5705))

### Upgrade instructions

- No changes required

## [0.31.2](https://github.com/dropseed/plain/releases/plain-oauth@0.31.2) (2025-10-20)

### What's changed

- Internal packaging improvements for development dependencies ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a))

### Upgrade instructions

- No changes required

## [0.31.1](https://github.com/dropseed/plain/releases/plain-oauth@0.31.1) (2025-10-17)

### What's changed

- `OAuthStateMissingError` is now raised when OAuth state is not found in the session, providing clearer error messaging ([72898275](https://github.com/dropseed/plain/commit/72898275))
- Updated error message to indicate possible causes like expired sessions or blocked cookies ([72898275](https://github.com/dropseed/plain/commit/72898275))

### Upgrade instructions

- No changes required

## [0.31.0](https://github.com/dropseed/plain/releases/plain-oauth@0.31.0) (2025-10-12)

### What's changed

- Preflight provider key check has been moved from the model to a standalone `CheckOAuthProviderKeys` preflight check class ([fdc5aee](https://github.com/dropseed/plain/commit/fdc5aee))
- Preflight check ID has been renamed from `oauth.provider_in_db_not_in_settings` to `oauth.provider_settings_missing` ([fdc5aee](https://github.com/dropseed/plain/commit/fdc5aee))

### Upgrade instructions

- No changes required

## [0.30.0](https://github.com/dropseed/plain/releases/plain-oauth@0.30.0) (2025-10-07)

### What's changed

- Model metadata is now defined using `model_options = models.Options(...)` instead of `class Meta` ([17a378d](https://github.com/dropseed/plain/commit/17a378d), [73ba469](https://github.com/dropseed/plain/commit/73ba469))

### Upgrade instructions

- No changes required

## [0.29.2](https://github.com/dropseed/plain/releases/plain-oauth@0.29.2) (2025-10-06)

### What's changed

- Added type annotations to improve IDE and type checker friendliness ([35fb8c4](https://github.com/dropseed/plain/commit/35fb8c4))
- Updated provider examples (Bitbucket, GitHub, GitLab) with proper type annotations ([50463b0](https://github.com/dropseed/plain/commit/50463b0))

### Upgrade instructions

- No changes required

## [0.29.1](https://github.com/dropseed/plain/releases/plain-oauth@0.29.1) (2025-10-02)

### What's changed

- Updated documentation examples to use `get_current_user()` instead of `request.user` ([f6278d9](https://github.com/dropseed/plain/commit/f6278d9bb4))

### Upgrade instructions

- No changes required

## [0.29.0](https://github.com/dropseed/plain/releases/plain-oauth@0.29.0) (2025-10-02)

### What's changed

- Removed direct access to `request.user` and `request.session` attributes in favor of using `get_request_user()` and `get_request_session()` functions ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))
- Removed dependency on `AuthenticationMiddleware` from test settings ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- If you have custom OAuth providers or views that access `request.user`, update them to use `get_request_user(request)` from `plain.auth`
- If you have custom OAuth providers that access `request.session`, update them to use `get_request_session(request)` from `plain.sessions`

## [0.28.0](https://github.com/dropseed/plain/releases/plain-oauth@0.28.0) (2025-09-30)

### What's changed

- `HttpRequest` has been renamed to `Request` throughout the OAuth provider classes ([cd46ff2](https://github.com/dropseed/plain/commit/cd46ff2003))

### Upgrade instructions

- If you have custom OAuth providers that override methods like `get_authorization_url_params`, `get_oauth_token`, `get_callback_url`, or any other methods that accept a request parameter, update the type hint from `HttpRequest` to `Request`
- Update any imports of `HttpRequest` in custom OAuth provider code to import `Request` instead from `plain.http`

## [0.27.0](https://github.com/dropseed/plain/releases/plain-oauth@0.27.0) (2025-09-25)

### What's changed

- The `OAuthConnection.check()` method has been replaced with `OAuthConnection.preflight()` as part of the new preflight system ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))
- Preflight check IDs have been renamed from numeric format (e.g., `plain.oauth.E001`) to descriptive names (e.g., `oauth.provider_in_db_not_in_settings`) ([cd96c97](https://github.com/dropseed/plain/commit/cd96c97b25))
- Preflight messages now provide clearer fix instructions directly in the `fix` attribute ([c7cde12](https://github.com/dropseed/plain/commit/c7cde12149))

### Upgrade instructions

- If you have custom code that calls `OAuthConnection.check()`, update it to use `OAuthConnection.preflight()` instead
- If you have code that references specific preflight check IDs (e.g., `plain.oauth.E001`), update them to use the new descriptive format (e.g., `oauth.provider_in_db_not_in_settings`)

## [0.26.0](https://github.com/dropseed/plain/releases/plain-oauth@0.26.0) (2025-09-12)

### What's changed

- Model queries now use `.query` instead of `.objects` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version increased to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Update any custom code that references `OAuthConnection.objects` to use `OAuthConnection.query` instead

## [0.25.1](https://github.com/dropseed/plain/releases/plain-oauth@0.25.1) (2025-08-22)

### What's changed

- Updated admin navigation to place icons on sections rather than individual items ([5a6479a](https://github.com/dropseed/plain/commit/5a6479ac79))

### Upgrade instructions

- No changes required

## [0.25.0](https://github.com/dropseed/plain/releases/plain-oauth@0.25.0) (2025-08-19)

### What's changed

- Removed requirement for manual `{{ csrf_input }}` in OAuth forms - CSRF protection now uses `Sec-Fetch-Site` headers automatically ([9551508](https://github.com/dropseed/plain/commit/955150800c))

### Upgrade instructions

- Remove `{{ csrf_input }}` from any OAuth forms in your templates (login, connect, disconnect forms) - CSRF protection is now handled automatically

## [0.24.2](https://github.com/dropseed/plain/releases/plain-oauth@0.24.2) (2025-08-05)

### What's changed

- Updated documentation to use `plain` commands instead of `python manage.py` references ([8071854](https://github.com/dropseed/plain/commit/8071854d61))
- Improved README with better structure, table of contents, and more comprehensive examples ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))
- Fixed router setup documentation in URLs section ([48caf10](https://github.com/dropseed/plain/commit/48caf105da))

### Upgrade instructions

- No changes required

## [0.24.1](https://github.com/dropseed/plain/releases/plain-oauth@0.24.1) (2025-07-23)

### What's changed

- Added a nav icon to the OAuth admin interface ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0e2c))

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-oauth@0.24.0) (2025-07-22)

### What's changed

- Migrations updated to use the new `PrimaryKeyField` instead of `BigAutoField` ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))

### Upgrade instructions

- No changes required.

## [0.23.0](https://github.com/dropseed/plain/releases/plain-oauth@0.23.0) (2025-07-18)

### What's changed

- Migrations have been restarted to consolidate the migration history into a single initial migration ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainoauth` after upgrading to clean up old migration records

## [0.22.0](https://github.com/dropseed/plain/releases/plain-oauth@0.22.0) (2025-06-23)

### What's changed

- Updated `OAuthConnection.check()` to accept a single `database` argument instead of the older `databases` list, matching the new single `DATABASE` setting used across the Plain stack ([d346d81](https://github.com/dropseed/plain/commit/d346d81))

### Upgrade instructions

- No changes required.
