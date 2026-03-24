---
related:
  - diagnose-command
  - ../postgres-first-data-layer/fk-remove-auto-index
---

# Preflight index checks

Code-level preflight checks that inspect model definitions (no database connection needed) and run during `plain check` / deploy.

## Checks

### Missing FK index coverage (warning)

For each ForeignKey field, check if the column is the leading column of any declared index or constraint on the model. If not, warn:

```
plainobserver.Log: FK field "trace" has no index coverage.
  Add an Index on ["trace"] or ensure a constraint covers it.
```

Without an index, JOINs on this FK do sequential scans, and ON DELETE CASCADE/PROTECT checks on the parent table are slow.

This is the safety net for removing FK auto-indexing — catches the problem at development time before it reaches the database.

### Duplicate index detection (warning)

For each model, collect all index column lists (from explicit indexes, constraint-backing indexes, and FK auto-indexes if they still exist) and check for prefix redundancy:

```
plainadmin.PinnedNavItem: Index on ["user"] is redundant with UniqueConstraint on ["user", "view_name"].
```

A prefix-duplicate index is pure write overhead — Postgres maintains it on every write but never uses it for reads, since the longer index covers all the same queries.

## Implementation

Both checks work by inspecting `Model._meta` — fields, indexes, and constraints are all available without a database connection. The check runs during `plain check` as part of the preflight system.

## Relationship to diagnose command

Preflight catches structural mistakes before they reach the database. The `diagnose` command catches the same things on existing databases (old migrations, manual DDL, drift). They overlap on FK/duplicate coverage — belt and suspenders.
