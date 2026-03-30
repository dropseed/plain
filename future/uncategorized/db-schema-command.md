---
---

# Schema inspection command

`plain postgres schema` for quick inspection of actual database state using model names instead of table names.

## Done

`plain postgres schema <ModelName>` is implemented — shows column types, constraints, and indexes for a model's table. Accepts model name, qualified name, or table name.

## Remaining

### `plain postgres tables`

List all tables with row counts and sizes.

```
$ plain postgres tables

  Table                              Rows    Size
  ──────────────────────────────────────────────────
  pullrequests_pullrequest          12,847   4.2 MB
  repos_repo                         1,203   896 kB
  organizations_organization           247    96 kB
  users_user                           189    64 kB
  plainmigrations                       42    16 kB
  ...

  18 tables, 14,528 rows, 5.3 MB total
```
