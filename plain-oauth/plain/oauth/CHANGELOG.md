# plain-oauth changelog

## [0.23.0](https://github.com/dropseed/plain/releases/plain-oauth@0.23.0) (2025-07-18)

### What's changed

- Migrations have been restarted to consolidate the migration history into a single initial migration ([484f1b6](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainoauth` after upgrading to clean up old migration records

## [0.22.0](https://github.com/dropseed/plain/releases/plain-oauth@0.22.0) (2025-06-23)

### What's changed

- Updated `OAuthConnection.check()` to accept a single `database` argument instead of the older `databases` list, matching the new single `DATABASE` setting used across the Plain stack ([d346d81](https://github.com/dropseed/plain/commit/d346d81))

### Upgrade instructions

- No changes required.
