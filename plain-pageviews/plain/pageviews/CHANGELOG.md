# plain-pageviews changelog

## [0.25.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.25.0) (2025-10-17)

### What's changed

- The pageview cleanup chore has been rewritten as an abstract base class for consistency with the broader Plain framework ([c4466d3](https://github.com/dropseed/plain/commit/c4466d3c6068b270ad3bcd1e5953b8a124a0dbf6))

### Upgrade instructions

- No changes required

## [0.24.1](https://github.com/dropseed/plain/releases/plain-pageviews@0.24.1) (2025-10-10)

### What's changed

- Updated session handling to use the new `SessionNotAvailable` exception from `plain-sessions` for better error messaging ([fe47d8d](https://github.com/dropseed/plain/commit/fe47d8d8f805c770b7aa9cbad67b5a51faddffc4))

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.24.0) (2025-10-07)

### What's changed

- Model metadata definition changed from `class Meta` to `model_options` descriptor ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb295f6de3fa1e9b2f476d3c11e3f21c), [73ba469](https://github.com/dropseed/plain/commit/73ba469ba052e054ac9cce4a054250b82e9206fb))

### Upgrade instructions

- No changes required

## [0.23.2](https://github.com/dropseed/plain/releases/plain-pageviews@0.23.2) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package for better IDE support and type checking ([c87ca27](https://github.com/dropseed/plain/commit/c87ca27ed2caff71d862d28a7e489031cb7beeb0))

### Upgrade instructions

- No changes required

## [0.23.1](https://github.com/dropseed/plain/releases/plain-pageviews@0.23.1) (2025-10-02)

### What's changed

- Updated to use new `get_request_user()` and `get_request_session()` helper functions for better compatibility and error handling ([2663c49](https://github.com/dropseed/plain/commit/2663c494043a3ecf317e5ce3340fde217366e0b8))

### Upgrade instructions

- No changes required

## [0.23.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.23.0) (2025-09-26)

### What's changed

- Removed the unused `uuid` field from the `Pageview` model ([c25c3fd](https://github.com/dropseed/plain/commit/c25c3fd816c6dbf14a145a70bc025f328845f5e7))

### Upgrade instructions

- No changes required

## [0.22.0](https://github.com/dropseed/plain/releases/plain-pageviews@0.22.0) (2025-09-25)

### What's changed

- Added UTM parameter tracking with automatic extraction of `utm_source`, `utm_medium`, and `utm_campaign` from URLs ([15547a7](https://github.com/dropseed/plain/commit/15547a7697f3298c0c2e71f488e56aec83ba4717))
- Added support for simple `ref` parameter as an alternative to UTM tracking ([15547a7](https://github.com/dropseed/plain/commit/15547a7697f3298c0c2e71f488e56aec83ba4717))
- Added auto-detection of tracking IDs from major ad platforms (Google Ads `gclid`, Facebook `fbclid`, Microsoft `msclkid`, TikTok `ttclid`, Twitter `twclid`) ([15547a7](https://github.com/dropseed/plain/commit/15547a7697f3298c0c2e71f488e56aec83ba4717))
- Added server-side pageview tracking via `Pageview.create_from_request()` method ([1944ff7](https://github.com/dropseed/plain/commit/1944ff7bbafba9ca046892b242bf4d6660b832c7))
- Added new `source`, `medium`, and `campaign` fields to the Pageview model with database indexes ([15547a7](https://github.com/dropseed/plain/commit/15547a7697f3298c0c2e71f488e56aec83ba4717))

### Upgrade instructions

- No changes required

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
