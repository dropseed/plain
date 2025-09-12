# plain-oauth changelog

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
