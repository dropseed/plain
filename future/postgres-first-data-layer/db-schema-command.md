---
related:
  - migrations-schema-check
---

# Schema inspection command

`plain postgres schema` for quick inspection of actual database state using model names instead of table names.

## Commands

### `plain postgres schema <ModelName>`

Show column types, constraints, and indexes for a model's table.

```
$ plain postgres schema Organization

organizations_organization (16 columns, 247 rows, 96 kB)

  Column                    Type                       Nullable  Default
  ─────────────────────────────────────────────────────────────────────────
  id                        bigint                     not null  generated
  host_type                 character varying(255)     not null
  host_id                   character varying(255)     not null
  name                      character varying(255)     not null
  gitlab_webhook_secret     character varying(64)      not null
  host_api_token            text                       not null
  ...

  Indexes:
    organizations_organization_pkey PRIMARY KEY (id)
    unique_organization_host_id UNIQUE (host_type, host_id)

  Foreign keys referencing this table:
    repos_repo.organization_id → id
```

Accepts model name (`Organization`), qualified name (`organizations.Organization`), or table name (`organizations_organization`).

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

## Why not just `plain postgres shell`

`plain postgres shell` already exists and opens psql. This is for when you want a quick look without an interactive session — scriptable, uses model names, and could later show expected-vs-actual if `migrations check-schema` is implemented.
