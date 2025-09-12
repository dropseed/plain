# plain-support changelog

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
