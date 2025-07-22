# plain-support changelog

## [0.14.0](https://github.com/dropseed/plain/releases/plain-support@0.14.0) (2025-07-22)

### What's changed

- Database models now use the new `PrimaryKeyField` instead of `BigAutoField` for primary keys ([4b8fa6aef1](https://github.com/dropseed/plain/commit/4b8fa6aef1))

### Upgrade instructions

- No changes required

## [0.13.0](https://github.com/dropseed/plain/releases/plain-support@0.13.0) (2025-07-18)

### What's changed

- Migrations have been restarted and consolidated into a single initial migration file ([484f1b6e93](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainsupport` to update your migration history and remove references to the old migration files

## [0.12.3](https://github.com/dropseed/plain/releases/plain-support@0.12.3) (2025-06-24)

### What's changed

- No user-facing changes. Internal cleanup of CHANGELOG formatting and linting (e1f5dd3, 9a1963d, 82710c3).

### Upgrade instructions

- No changes required
