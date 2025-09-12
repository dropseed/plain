# plain-pageviews changelog

## [0.21.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.21.0) (2025-09-12)

### What's changed

- Model manager has been renamed from `objects` to `query` for consistency with the broader Plain framework ([037a239](https://github.com/dropseed/plain/commit/037a239ef4711c4477a211d63c57ad8414096301))

### Upgrade instructions

- Replace any usage of `Pageview.objects` with `Pageview.query` in your code (e.g., `Pageview.objects.filter()` becomes `Pageview.query.filter()`)

## [0.20.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.20.0) (2025-09-09)

### What's changed

- Pageviews now use session ID instead of session key for tracking ([a58e2a9](https://github.com/dropseed/plain/commit/a58e2a9))
- Python 3.13 is now the minimum required version ([d86e307](https://github.com/dropseed/plain/commit/d86e307))

### Upgrade instructions

- No changes required

## [0.19.1](https://github.com/dropseed/plain/releases/plain-pageviews@0.19.1) (2025-08-22)

### What's changed

- Updated admin navigation to display icons on sections instead of individual items ([5a6479a](https://github.com/dropseed/plain/commit/5a6479a))

### Upgrade instructions

- No changes required

## [0.19.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.19.0) (2025-08-19)

### What's changed

- CSRF protection is no longer handled by `CsrfExemptViewMixin` ([2a50a91](https://github.com/dropseed/plain/commit/2a50a91))
- Updated README documentation with improved formatting and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1))

### Upgrade instructions

- No changes required

## [0.18.1](https://github.com/dropseed/plain/releases/plain-pageviews@0.18.1) (2025-07-23)

### What's changed

- Added an "eye" icon to the pageviews navigation in admin interface ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.18.0) (2025-07-22)

### What's changed

- Replaced `pk` alias and `BigAutoField` with a single automatic `PrimaryKeyField` for model consistency ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.17.0) (2025-07-18)

### What's changed

- Migrations have been restarted and consolidated into a single initial migration that includes all model changes and database indexes ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6))

### Upgrade instructions

- Run `plain migrate --prune plainpageviews` to remove old migration records and apply the consolidated migration

## [0.16.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.16.0) (2025-07-07)

### What's changed

- Reduced the maximum length of `Pageview.url` from 1024 to 768 characters to honor the 3072-byte index limit on MySQL and ensure migrations succeed on all supported databases ([6322400](https://github.com/dropseed/plain/commit/6322400)).

### Upgrade instructions

- No changes required

## [0.15.6](https://github.com/dropseed/plain/releases/plain-pageviews@0.15.6) (2025-06-26)

### What's changed

- Added an initial `CHANGELOG.md` for the package and performed minor documentation linting ([82710c3](https://github.com/dropseed/plain/commit/82710c3)).

### Upgrade instructions

- No changes required
