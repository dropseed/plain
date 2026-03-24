---
related:
  - ../postgres-insights
---

# Rename `plain db` → `plain postgres`

The framework is Postgres-only. `plain db` is a generic name inherited from Django's multi-backend world. Rename to `plain postgres` — existing commands (`shell`, `wait`, `drop-unknown-tables`, `backups`) move under it.

This also creates a natural namespace for Postgres-specific insight commands that wouldn't make sense under a generic `db` prefix.

## Open questions

- `plain postgres` or `plain pg` for brevity? Heroku uses `pg`, but `postgres` is more explicit.
