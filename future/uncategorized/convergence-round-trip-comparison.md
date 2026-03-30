---
related:
  - postgres-native-schema
---

# Convergence: round-trip comparison via temp tables

Replace string normalization in schema convergence with round-trip comparison through PostgreSQL, eliminating an entire class of false-positive drift reports.

## Problem

Schema convergence compares model-generated SQL against PostgreSQL's `pg_get_indexdef`/`pg_get_constraintdef` output. These two generators produce semantically identical but syntactically different SQL — type casts (`''::text` vs `''`), parenthesization (`(LOWER(col))` vs `lower(col)`), quoting. The current approach uses structured comparison with targeted normalization, which works but requires a new fix for each new formatting difference PostgreSQL introduces.

## Proposal

For each index or constraint being compared, create it on an empty temp table and read back its definition using the same `pg_get_indexdef` that produced the actual definition. Both sides go through PostgreSQL's own serializer, so they're guaranteed to match if semantically equivalent — zero normalization needed.

```
Model → ORM compiler → SQL → execute on temp table → pg_get_indexdef → compare
                                                                          ↕
Database →                                          pg_get_indexdef → compare
```

### Implementation sketch

1. Per table: `CREATE TEMP TABLE _pc_{table} (LIKE {table})`
2. Per constraint/index: create on temp table, `pg_get_indexdef`, drop
3. Compare the body after `USING method` (strips table name/schema prefix)
4. Drop temp table after all comparisons for that table

Temp tables are session-local, empty (instant DDL), and auto-cleaned at session end.

## Why not now

The `schema` command is currently read-only. Temp table creation requires `TEMPORARY` privilege, which is granted to `PUBLIC` by default in PostgreSQL but can be revoked. Environments where this matters:

- **Enterprise deployments** with locked-down DBA policies (`REVOKE TEMPORARY ON DATABASE ... FROM PUBLIC`)
- **Read replicas** — completely read-only, no DDL
- **Read-only transaction modes** (`default_transaction_read_only = on`)
- **PgBouncer transaction mode** — needs careful cleanup to avoid leaking temp tables onto pooled connections

For a framework shipping to self-hosted enterprise customers, the read-only guarantee of `schema` is worth preserving until we have evidence that the structured comparison approach is hitting too many edge cases.

## When to revisit

If we accumulate more than 2-3 normalization fixes in `normalize_check_definition` / `normalize_expression` / `_parse_index_definition`, or if a PostgreSQL version changes `pg_get_indexdef` formatting in a way that breaks structured comparison broadly, the maintenance cost tips in favor of the round-trip approach.

At that point, consider making it opt-in (`--round-trip` flag or a setting) so users in restricted environments can fall back to the current behavior.
