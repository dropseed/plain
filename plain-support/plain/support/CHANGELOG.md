# plain-support changelog

## [0.23.0](https://github.com/dropseed/plain/releases/plain-support@0.23.0) (2025-11-13)

### What's changed

- Model field definitions now use type stubs with explicit type annotations for improved IDE support and type checking ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc))

### Upgrade instructions

- No changes required

## [0.22.0](https://github.com/dropseed/plain/releases/plain-support@0.22.0) (2025-11-12)

### What's changed

- Improved type checking compatibility with added type ignore comments for ORM patterns ([f4dbcef](https://github.com/dropseed/plain/commit/f4dbcef))

### Upgrade instructions

- No changes required

## [0.21.2](https://github.com/dropseed/plain/releases/plain-support@0.21.2) (2025-11-03)

### What's changed

- Iframe JavaScript now includes CSP nonce for improved Content Security Policy compatibility ([7b8f8d2](https://github.com/dropseed/plain/commit/7b8f8d2fe4))

### Upgrade instructions

- No changes required

## [0.21.1](https://github.com/dropseed/plain/releases/plain-support@0.21.1) (2025-10-31)

### What's changed

- Added BSD-3-Clause license file and declaration to package metadata ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.21.0](https://github.com/dropseed/plain/releases/plain-support@0.21.0) (2025-10-29)

### What's changed

- Updated iframe view to use `None` instead of empty string to remove `X-Frame-Options` header, aligning with new response header handling ([5199383](https://github.com/dropseed/plain/commit/5199383128))

### Upgrade instructions

- No changes required

## [0.20.0](https://github.com/dropseed/plain/releases/plain-support@0.20.0) (2025-10-07)

### What's changed

- Model configuration now uses `model_options` descriptor instead of `class Meta` ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb), [73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.19.1](https://github.com/dropseed/plain/releases/plain-support@0.19.1) (2025-10-06)

### What's changed

- Added type annotations throughout the package for improved IDE support and type checking ([c87ca27](https://github.com/dropseed/plain/commit/c87ca27ed2))

### Upgrade instructions

- No changes required

## [0.19.0](https://github.com/dropseed/plain/releases/plain-support@0.19.0) (2025-10-02)

### What's changed

- `SupportFormView` now uses `AuthViewMixin` for better authentication handling and accesses user via `self.user` instead of `self.request.user` ([154ee10](https://github.com/dropseed/plain/commit/154ee10375))

### Upgrade instructions

- If you have custom support views that inherit from `SupportFormView` and access `self.request.user` directly, update them to use `self.user` instead

## [0.18.0](https://github.com/dropseed/plain/releases/plain-support@0.18.0) (2025-09-26)

### What's changed

- Removed unused `uuid` field from `SupportFormEntry` model ([331ce37](https://github.com/dropseed/plain/commit/331ce37992))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-support@0.17.0) (2025-09-12)

### What's changed

- Model managers have been renamed from `.objects` to `.query` throughout the codebase ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Python 3.13 is now the minimum required version ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Replace any usage of `.objects` with `.query` when working with Plain models (e.g., `SupportFormEntry.objects.all()` becomes `SupportFormEntry.query.all()`)

## [0.16.0](https://github.com/dropseed/plain/releases/plain-support@0.16.0) (2025-08-22)

### What's changed

- Admin interface navigation icon is now properly positioned on the section when sections are present ([5a6479ac79](https://github.com/dropseed/plain/commit/5a6479ac79))
- Improved iframe embed error state handling with better timeout logic and race condition prevention ([6bb1567a25](https://github.com/dropseed/plain/commit/6bb1567a25))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-support@0.15.0) (2025-08-19)

### What's changed

- Support forms now use Plain's new CSRF protection with `Sec-Fetch-Site` headers instead of CSRF tokens ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- `SupportIFrameView` no longer inherits from `CsrfExemptViewMixin`, using path-based CSRF exemption instead ([2a50a9154e](https://github.com/dropseed/plain/commit/2a50a9154e))
- Comprehensive README documentation updates with better structure, examples, and installation instructions ([4ebecd1856](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.14.1](https://github.com/dropseed/plain/releases/plain-support@0.14.1) (2025-07-23)

### What's changed

- Admin interface now displays a headset icon for the Support navigation section ([9e9f8b0e2c](https://github.com/dropseed/plain/commit/9e9f8b0e2c))

### Upgrade instructions

- No changes required

## [0.14.0](https://github.com/dropseed/plain/releases/plain-support@0.14.0) (2025-07-22)

### What's changed

- Database models now use the new `PrimaryKeyField` instead of `BigAutoField` for primary keys ([4b8fa6aef1](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-support@0.13.0) (2025-07-18)

### What's changed

- Migrations have been restarted and consolidated into a single initial migration file ([484f1b6e93](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainsupport` to update your migration history and remove references to the old migration files

## [0.12.3](https://github.com/dropseed/plain/releases/plain-support@0.12.3) (2025-06-24)

### What's changed

- No user-facing changes. Internal cleanup of CHANGELOG formatting and linting (e1f5dd3, 9a1963d, 82710c3).

### Upgrade instructions

- No changes required
