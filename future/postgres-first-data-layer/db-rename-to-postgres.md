---
related:
  - ../postgres-insights
---

# Rename `plain db` → `plain postgres`

Done. Changed `register_cli("db")` to `register_cli("postgres")`. All commands (`shell`, `wait`, `drop-unknown-tables`, `backups`, `diagnose`) now live under `plain postgres`.

Went with `plain postgres` over `plain pg` — more explicit, matches the package name.
