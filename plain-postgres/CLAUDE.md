# Developing plain-postgres

## PostgreSQL

Minimum supported version is **PostgreSQL 16** (enforced by preflight check). Use PG 16+ features freely.

When implementing database features, fetch the official PostgreSQL docs to verify behavior — don't assume SQL semantics from memory. Check both the minimum version docs and the latest for newer features worth adopting: https://www.postgresql.org/docs/

## psycopg3

The database driver is psycopg3 (`import psycopg`). Prefer its native APIs over hand-rolled abstractions.
