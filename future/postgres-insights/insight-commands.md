---
related:
  - diagnose-command
---

# Individual insight commands

Drill-down commands for when `diagnose` flags something:

- `plain postgres tables` — sizes, row counts, bloat
- `plain postgres indexes` — usage stats, duplicates, unused
- `plain postgres connections` — by state, user, application
- `plain postgres queries` — long-running, locks, outliers (requires `pg_stat_statements`)

The `schema` command is tracked separately in the data layer arc (`db-schema-command`).
