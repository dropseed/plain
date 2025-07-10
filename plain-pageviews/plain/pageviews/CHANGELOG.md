# plain-pageviews changelog

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
