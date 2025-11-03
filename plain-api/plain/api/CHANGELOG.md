# plain-api changelog

## [0.16.3](https://github.com/dropseed/plain/releases/plain-api@0.16.3) (2025-11-03)

### What's changed

- CLI command docstrings updated to match coding style guidelines ([fdb9e80](https://github.com/dropseed/plain/commit/fdb9e80103))
- Internal model configuration updated to use `_meta` descriptor pattern ([c75441e](https://github.com/dropseed/plain/commit/c75441eba7))

### Upgrade instructions

- No changes required

## [0.16.2](https://github.com/dropseed/plain/releases/plain-api@0.16.2) (2025-10-31)

### What's changed

- Added explicit BSD-3-Clause license metadata to package configuration ([8477355](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.16.1](https://github.com/dropseed/plain/releases/plain-api@0.16.1) (2025-10-20)

### What's changed

- Internal packaging configuration updated ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-api@0.16.0) (2025-10-07)

### What's changed

- Model configuration changed from `class Meta` to `model_options = models.Options()` descriptor ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))

### Upgrade instructions

- No changes required

## [0.15.2](https://github.com/dropseed/plain/releases/plain-api@0.15.2) (2025-10-06)

### What's changed

- Added type annotations throughout the package for improved IDE and type checker support ([41f6429](https://github.com/dropseed/plain/commit/41f6429892))

### Upgrade instructions

- No changes required

## [0.15.1](https://github.com/dropseed/plain/releases/plain-api@0.15.1) (2025-10-02)

### What's changed

- Updates docs references to `request.user`

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-api@0.15.0) (2025-09-25)

### What's changed

- Removed deprecated field types: `NullBooleanField` from OpenAPI schema generation ([345295d](https://github.com/dropseed/plain/commit/345295dc8a))

### Upgrade instructions

- If you were using `NullBooleanField` in your API forms, replace it with `BooleanField` with `required=False` and/or `allow_null=True` as appropriate

## [0.14.0](https://github.com/dropseed/plain/releases/plain-api@0.14.0) (2025-09-12)

### What's changed

- Model and related manager objects renamed from `objects` to `query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4711c4477a211d63c57ad8414096301))
- Minimum Python version updated to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb0d5e8f5001efccede4d58d0e26bfea))

### Upgrade instructions

- No changes required

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
