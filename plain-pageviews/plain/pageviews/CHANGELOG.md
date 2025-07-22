# plain-pageviews changelog

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
