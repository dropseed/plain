# plain-loginlink changelog

## [0.16.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.16.0) (2025-12-04)

### What's changed

- Internal refactoring of `ExpiringSigner` to use composition instead of inheritance for better type safety ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.15.0) (2025-11-24)

### What's changed

- Views now inherit from `AuthView` instead of using `AuthViewMixin` for improved type checking support ([569afd6](https://github.com/dropseed/plain/commit/569afd606d))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.14.0) (2025-11-13)

### What's changed

- The `expires_in` parameter in `dumps()` and `sign_object()` is now keyword-only and required ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa92))
- The `key` parameter in `loads()` is now keyword-only ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcefa92))

### Upgrade instructions

- Update any direct calls to `dumps()` to pass `expires_in` as a keyword argument (e.g., `dumps(obj, expires_in=3600)` instead of `dumps(obj, 3600)`)
- Update any direct calls to `loads()` to pass `key` as a keyword argument if specified (e.g., `loads(s, key="mykey")` instead of `loads(s, "mykey")`)

## [0.13.2](https://github.com/dropseed/plain/releases/plain-loginlink@0.13.2) (2025-10-31)

### What's changed

- Added BSD-3-Clause license to package metadata ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.13.1](https://github.com/dropseed/plain/releases/plain-loginlink@0.13.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations to improve IDE and type checker support ([634489d](https://github.com/dropseed/plain/commit/634489db6b))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.13.0) (2025-10-02)

### What's changed

- Login views now use `AuthViewMixin` to access user and session data instead of request attributes ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.12.0) (2025-09-12)

### What's changed

- Model managers renamed from `objects` to `query` for consistency with Plain framework ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version raised from 3.11 to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- README updated with proper formatting and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- Replace any custom usage of `User.objects` with `User.query` in your loginlink-related code

## [0.11.0](https://github.com/dropseed/plain/releases/plain-loginlink@0.11.0) (2025-07-22)

### What's changed

- Login link generation now uses `user.id` instead of `user.pk` for consistency ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required.

## [0.10.1](https://github.com/dropseed/plain/releases/plain-loginlink@0.10.1) (2025-06-23)

### What's changed

- No user-facing changes in this release.

### Upgrade instructions

- No changes required.
