---
labels:
  - plain-models
  - plain.views
---

# plain-models: Read-only transactions

- Use psycopg3's `connection.read_only = True` to enforce read-only transactions at the database level
- Any INSERT/UPDATE/DELETE/DDL in a read-only transaction raises a database error — catches accidental writes as bugs
- View-level opt-in: `read_only = True` attribute on views, similar to existing view mixins
- Could also provide a context manager: `with read_only_transaction():` for non-view code (jobs, scripts)
- GET/HEAD requests could default to read-only (opt-out with `read_only = False` on the view) — needs discussion on whether this should be automatic or explicit-only
- psycopg3 API: `connection.read_only` is a writable `bool | None` property, set before the transaction begins
- Integration point: set `read_only` on the connection after checkout, before the view runs, reset on return
