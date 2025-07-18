# plain-cache changelog

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
