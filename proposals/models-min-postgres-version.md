---
packages:
  - plain-models
---

# plain-models: Minimum PostgreSQL 16

- Define and enforce PostgreSQL 16 as the minimum supported version
- PG 14 reaches EOL Nov 2026, PG 15 in Nov 2027 — PG 16 (EOL Nov 2028) is a safe floor
- Enforcement: check `server_version` on first connection, raise a clear error if below 16
- Could run as a preflight check so it surfaces at startup, not on first query
- Documenting a minimum version unlocks psycopg3 features that require specific libpq/server versions (e.g., pipeline mode requires libpq 14+, prepared statement PgBouncer compat requires libpq 17+)
- Re-evaluate the floor annually as older versions reach EOL
