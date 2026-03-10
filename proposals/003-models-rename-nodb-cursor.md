---
packages:
  - plain-models
related:
  - 001-db-connection-pool
---

# Rename `_nodb_cursor` to `_maintenance_cursor`

## Problem

`_nodb_cursor` is a cryptic Django-ism. The name suggests "no database" but it actually connects to the PostgreSQL maintenance database (`postgres`) to run admin operations without touching the project's database.

## Current behavior

- `_nodb_cursor()` creates a temporary connection with `"DATABASE": None`, which connects to the `postgres` maintenance database
- If that fails, falls back to the configured project database with a warning
- Always uses `_use_pool=False` — bypasses connection pooling
- Used in exactly two places: `_create_test_db` and `_destroy_test_db`

## Proposed change

Rename `_nodb_cursor` to `_maintenance_cursor` — matches PostgreSQL's own terminology for the `postgres` database and makes the intent self-documenting.

The docstring can be shortened since the name now carries the meaning.
