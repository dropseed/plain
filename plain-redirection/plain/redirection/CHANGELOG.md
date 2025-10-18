# plain-redirection changelog

## [0.23.0](https://github.com/dropseed/plain/releases/plain-redirection@0.23.0) (2025-10-17)

### What's changed

- Chores have been rewritten as abstract base classes instead of plain functions ([c4466d3c](https://github.com/dropseed/plain/commit/c4466d3c))

### Upgrade instructions

- No changes required

## [0.22.0](https://github.com/dropseed/plain/releases/plain-redirection@0.22.0) (2025-10-07)

### What's changed

- Model configuration changed from `class Meta` to `_meta` descriptor, then to `model_options` attribute ([17a378dc](https://github.com/dropseed/plain/commit/17a378dc), [73ba469b](https://github.com/dropseed/plain/commit/73ba469b))

### Upgrade instructions

- No changes required

## [0.21.1](https://github.com/dropseed/plain/releases/plain-redirection@0.21.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations for improved IDE support and type checking ([c87ca27e](https://github.com/dropseed/plain/commit/c87ca27e))

### Upgrade instructions

- No changes required

## [0.21.0](https://github.com/dropseed/plain/releases/plain-redirection@0.21.0) (2025-09-12)

### What's changed

- Database manager `objects` attribute renamed to `query` for all models ([037a239e](https://github.com/dropseed/plain/commit/037a239e))
- Admin navigation icons updated to use consistent `arrow-right-circle` icon ([2aac07de](https://github.com/dropseed/plain/commit/2aac07de))
- Python 3.13 minimum requirement ([d86e307e](https://github.com/dropseed/plain/commit/d86e307e))

### Upgrade instructions

- Update all model queries from `.objects` to `.query` (e.g., `Redirect.objects.create()` becomes `Redirect.query.create()`, `RedirectLog.objects.all()` becomes `RedirectLog.query.all()`)

## [0.20.1](https://github.com/dropseed/plain/releases/plain-redirection@0.20.1) (2025-08-22)

### What's changed

- Admin navigation icons are now displayed on section headers instead of individual items for improved visual organization ([5a6479ac](https://github.com/dropseed/plain/commit/5a6479ac))

### Upgrade instructions

- No changes required

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
