# plain-api changelog

## [0.13.0](https://github.com/dropseed/plain/releases/plain-api@0.13.0) (2025-08-19)

### What's changed

- API views no longer use `CsrfExemptViewMixin` ([2a50a91](https://github.com/dropseed/plain/commit/2a50a9154e7fb72ea0dad860954af1f96117143e))
- Improved README documentation with better examples and installation instructions ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856f96afc09a2ad6887224ae94b1a7395))

### Upgrade instructions

- No changes required

## [0.12.0](https://github.com/dropseed/plain/releases/plain-api@0.12.0) (2025-07-22)

### What's changed

- The `APIKey` model now uses `PrimaryKeyField()` instead of `BigAutoField` for the primary key ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef126a15e48b5f85e0652adf841eb7b5c))

### Upgrade instructions

- No changes required

## [0.11.0](https://github.com/dropseed/plain/releases/plain-api@0.11.0) (2025-07-18)

### What's changed

- Migrations have been restarted with all fields consolidated into the initial migration ([484f1b6e93](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainapi` to remove old migration records and apply the consolidated migration

## [0.10.1](https://github.com/dropseed/plain/releases/plain-api@0.10.1) (2025-06-24)

### What's changed

- Added an initial CHANGELOG for plain-api (documentation only, no functional changes) ([82710c3](https://github.com/dropseed/plain/commit/82710c3))

### Upgrade instructions

- No changes required
