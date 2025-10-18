# plain-cache changelog

## [0.20.0](https://github.com/dropseed/plain/releases/plain-cache@0.20.0) (2025-10-17)

### What's changed

- Chores have been rewritten as abstract base classes instead of function-based decorators ([c4466d3](https://github.com/dropseed/plain/commit/c4466d3c60))

### Upgrade instructions

- If you have custom chores defined, update them from function-based decorators to class-based chores that inherit from `Chore` and implement a `run()` method (see [plain.chores documentation](https://github.com/dropseed/plain/tree/master/plain/plain/chores))

## [0.19.0](https://github.com/dropseed/plain/releases/plain-cache@0.19.0) (2025-10-07)

### What's changed

- Model configuration updated from `class Meta` to `model_options` descriptor for improved type safety ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- QuerySet is now a proper descriptor with enhanced type annotations ([2578301](https://github.com/dropseed/plain/commit/2578301819))
- Improved type safety by removing `type: ignore` comments throughout the package ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))

### Upgrade instructions

- No changes required

## [0.18.1](https://github.com/dropseed/plain/releases/plain-cache@0.18.1) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout the package, achieving 100% type coverage ([154d4c4](https://github.com/dropseed/plain/commit/154d4c44fc))

### Upgrade instructions

- No changes required

## [0.18.0](https://github.com/dropseed/plain/releases/plain-cache@0.18.0) (2025-09-12)

### What's changed

- Model manager API has been updated from `.objects` to `.query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Minimum Python version requirement raised to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))

### Upgrade instructions

- Update any custom code that references `CachedItem.objects` to use `CachedItem.query` instead

## [0.17.2](https://github.com/dropseed/plain/releases/plain-cache@0.17.2) (2025-08-22)

### What's changed

- Updated README.md with improved documentation structure and formatting ([4ebecd1](https://github.com/dropseed/plain/commit/4ebecd1856))
- Admin interface icon positioning updated to be on nav sections ([5a6479a](https://github.com/dropseed/plain/commit/5a6479ac79))

### Upgrade instructions

- No changes required

## [0.17.1](https://github.com/dropseed/plain/releases/plain-cache@0.17.1) (2025-07-23)

### What's changed

- Added archive icon to the cache admin interface navigation ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0))

### Upgrade instructions

- No changes required

## [0.17.0](https://github.com/dropseed/plain/releases/plain-cache@0.17.0) (2025-07-22)

### What's changed

- Database migrations updated to use new PrimaryKeyField instead of BigAutoField ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))
- Admin interface now uses `id` instead of `pk` for queryset ordering

### Upgrade instructions

- No changes required

## [0.16.0](https://github.com/dropseed/plain/releases/plain-cache@0.16.0) (2025-07-18)

### What's changed

- Added OpenTelemetry tracing support for all cache operations (get, set, delete, exists) ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))

### Upgrade instructions

- No changes required

## [0.15.0](https://github.com/dropseed/plain/releases/plain-cache@0.15.0) (2025-07-18)

### What's changed

- Database migrations have been restarted and consolidated into a single initial migration ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6e93))
- Admin interface query optimization restored using `.only()` to fetch minimal fields for list views

### Upgrade instructions

- Run `plain migrate --prune plaincache` to handle the migration restart and remove old migration files

## [0.14.3](https://github.com/dropseed/plain/releases/plain-cache@0.14.3) (2025-06-26)

### What's changed

- No user-facing changes. This release only adds and formats the package CHANGELOG file (82710c3).

### Upgrade instructions

- No changes required
