---
related:
  - migrations-rename-app-column
---

# migrations: Schema drift detection

Done. Implemented as `plain postgres schema` with two modes:

- `plain postgres schema` — shows expected DB schema from model definitions (tables, columns, types, indexes, constraints)
- `plain postgres schema --check` — compares expected schema against actual DB, reports drift (type mismatches, nullability, missing/extra columns, orphan indexes)
- `plain postgres schema [model_label]` — filter to a single model

Design decision: drift is never intentional (Plain owns the schema, no unmanaged models). The `--check` mode exits non-zero on any mismatch, suitable for CI.
