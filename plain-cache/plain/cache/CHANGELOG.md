# plain-cache changelog

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
