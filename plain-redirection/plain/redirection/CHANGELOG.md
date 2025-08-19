# plain-redirection changelog

## [0.20.0](https://github.com/dropseed/plain/releases/plain-redirection@0.20.0) (2025-08-19)

### What's changed

- Added comprehensive README documentation with usage examples, API reference, and installation instructions ([4ebecd18](https://github.com/dropseed/plain/commit/4ebecd18))
- Removed manual CSRF token requirement from admin forms as part of framework-wide CSRF improvements ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- Updated package description in pyproject.toml to "A flexible URL redirection system with admin interface and logging" ([4ebecd18](https://github.com/dropseed/plain/commit/4ebecd18))

### Upgrade instructions

- No changes required

## [0.19.0](https://github.com/dropseed/plain/releases/plain-redirection@0.19.0) (2025-07-23)

### What's changed

- Admin navigation now includes Bootstrap icons for redirect, log, and 404 log sections ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-redirection@0.18.0) (2025-07-22)

### What's changed

- Database models now use the simplified `PrimaryKeyField` instead of `BigAutoField` for primary keys ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-redirection@0.17.0) (2025-07-18)

### What's changed

- Migration files have been consolidated into a single initial migration ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6)).

### Upgrade instructions

- If you have an existing installation with applied migrations, run `plain migrate --prune plainredirection` to handle the migration consolidation (both in development and production environments).

## [0.16.2](https://github.com/dropseed/plain/releases/plain-redirection@0.16.2) (2025-06-24)

### What's changed

- No user-facing changes. This release only updates internal CHANGELOG formatting ([e1f5dd3](https://github.com/dropseed/plain/commit/e1f5dd3), [9a1963d](https://github.com/dropseed/plain/commit/9a1963d)).

### Upgrade instructions

- No changes required
