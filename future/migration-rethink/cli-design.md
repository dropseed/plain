# CLI design

**This is the authoritative CLI reference.** sync-command.md covers the sync behavior/semantics in depth; this doc defines the actual command surface.

Everything under `plain postgres`. No top-level shortcuts.

Two primary commands: `schema` (understand your database) and `sync` (update your database). Everything else is infrastructure or diagnostics.

## The dev loop

```bash
# Edit model...
plain postgres schema            # see what's different
plain postgres schema --make     # generate migration files
plain postgres sync              # apply everything
```

## The deploy

```bash
plain postgres sync
```

## Primary commands

### `plain postgres sync`

Make the database match the code. Idempotent.

```
$ plain postgres sync

Migrations:
  ✓ 20240301_140000 create_orders
  ✓ 20240315_110000 add_priority_field

Schema:
  ✓ orders — created index orders_user_id_idx
  ✓ orders — created FK constraint orders_author_fk
  ✓ orders.priority — backfilled 47 rows with default 'normal'
  ✓ orders.priority — applied NOT NULL
```

Internally: apply pending migrations (batch transaction) → backfill NULLs where model has default → converge indexes, constraints, NOT NULL. The user just sees one operation.

On an empty database, creates everything from model definitions, replays RunPython/RunSQL data operations, then marks all migrations as applied. See fresh-db-from-models.md for the full design.

Handles stale migration records automatically. If convergence partially failed, run again to retry.

```
$ plain postgres sync

Schema:
  ✗ orders.legacy_ref — NOT NULL, no default, 1,200 NULLs
    Write a data migration to populate this column.
```

**Flags:**

- `--check` — exit non-zero if anything is pending (for CI: "is the DB fully in sync?")
- `--dry-run` — show what would happen
- `--fake <timestamp>` — mark a migration as applied without running it (escape hatch)

### `plain postgres schema`

Show the database state using model names. Highlights differences between models and DB.

```
$ plain postgres schema

orders (4 columns, 1,247 rows, 96 kB)

  Column        Type      Nullable  Default
  ───────────────────────────────────────────
  ✓ id          bigint    NOT NULL  generated
  ✓ title       text      NOT NULL
  ✓ status      text      NOT NULL
  + priority    text      NULL                  ← not in database

  Indexes:
    ✓ orders_pkey PRIMARY KEY (id)
    + orders_user_id_idx (author_id)            ← missing

  Constraints:
    ✓ orders_pkey
    + orders_author_fk FK (author_id) → users   ← missing

Run `plain postgres schema --make` to create a migration.
Run `plain postgres sync` to apply all changes.
```

**Arguments:**

- `<ModelName>` — show one model (accepts model name, qualified name, or table name)
- No argument — summary of all models

**Flags:**

- `--make` — generate `.sql` migration files for column/table changes
- `--make --name <name>` — custom migration name suffix
- `--make --empty` — create empty `.py` migration file (for data operations / RunPython)
- `--check` — exit non-zero if any differences (for CI: "are there unmigrated model changes?")
- `--sql` — show the DDL that would be executed

### `--make` discoverability: why not a top-level `makemigrations` command?

`postgres schema --make` replaces `makemigrations`. This is intentional — generating migrations is viewing the schema diff and then acting on it, not a separate workflow. The flag makes the relationship between "see the diff" and "capture the diff" explicit.

**How other frameworks handle the "generate migration" verb:**

| Framework | Command                             | Pattern                                                                       |
| --------- | ----------------------------------- | ----------------------------------------------------------------------------- |
| Rails     | `rails generate migration <name>`   | Explicit top-level command. Manual — generates a stub, developer fills it in. |
| Laravel   | `php artisan make:migration <name>` | Explicit top-level command. Same manual stub pattern as Rails.                |
| Ecto      | `mix ecto.gen.migration <name>`     | Explicit top-level command. Manual stub.                                      |
| Django    | `python manage.py makemigrations`   | Explicit top-level command. Auto-detects changes from models.                 |
| Prisma    | `prisma migrate dev`                | Part of the dev workflow — auto-generates as a side effect.                   |
| Atlas     | `atlas migrate diff <name>`         | Explicit command. Auto-detects changes from schema definition.                |

Plain's `--make` is closest to Prisma's approach (generation as part of the schema workflow) but more explicit (you choose when to generate). The key difference from Rails/Laravel/Ecto is that Plain auto-detects changes from models like Django and Atlas do — there's no manual stub to fill in for schema changes. The `--make` flag captures what `postgres schema` already computed.

**Decision: `--make` is sufficient. No alias needed.** The flag is prominently suggested in `postgres schema` output (`Run 'plain postgres schema --make' to create a migration`), so discoverability is built into the workflow. Adding a `makemigrations` alias would create two ways to do the same thing and blur the "everything under `plain postgres`" principle. Developers coming from Django will see the suggestion on their first `postgres schema` run.

### Two `--check` modes

Both useful in CI, checking different things:

- `postgres schema --check` — "are there model changes not yet captured in migration files?" (run after code changes, before merge)
- `postgres sync --check` — "are there pending migrations or convergence work?" (run at deploy time)

## Other commands

### `plain postgres shell`

Open psql. Already exists.

### `plain postgres reset`

Drop, create, sync. For development.

```
$ plain postgres reset

Drop database "myapp_dev"? [y/n] y
  ✓ Dropped
  ✓ Created
  ✓ Synced (12 tables, 8 indexes, 5 constraints)
```

**Flags:**

- `--yes` — skip confirmation

### `plain postgres wait`

Wait for database to be ready. For startup scripts / Docker. Already exists.

### `plain postgres diagnose`

Run health checks — unused indexes, missing FK indexes, sequence exhaustion, bloat, etc. Already exists.

### `plain postgres backups`

Local database backups. Already exists as a subgroup: `list`, `create`, `restore`, `delete`, `clear`.

## Preflight integration

`plain check` includes:

- `postgres schema --check` — unmigrated model changes
- `postgres sync --check` — pending sync work

`plain check --skip-db` to skip when no DB is available.

## What's removed

| Gone                      | Replaced by                                         |
| ------------------------- | --------------------------------------------------- |
| `plain migrate`           | `postgres sync`                                     |
| `plain makemigrations`    | `postgres schema --make`                            |
| `migrations list`         | `postgres schema` (shows pending), `sync --dry-run` |
| `migrations squash`       | Not needed                                          |
| `migrations apply`        | `postgres sync`                                     |
| `migrations apply --fake` | `postgres sync --fake`                              |
| `migrations prune`        | `postgres sync` (automatic)                         |
| `drop-unknown-tables`     | `postgres diagnose` can report                      |

There are no standalone `migrations apply`, `migrations list`, or `postgres converge` subcommands. `postgres sync` is the single entry point for all write operations, with `--dry-run` replacing `list` and individual steps being implementation details rather than user-facing commands. Fine-grained control is available via `--fake` for escape hatches, not via separate subcommands.

## Full command list

| Command             | Purpose                                                       |
| ------------------- | ------------------------------------------------------------- |
| `postgres sync`     | Make DB match code                                            |
| `postgres schema`   | Show DB state + differences (`--make` to generate migrations) |
| `postgres shell`    | Open psql                                                     |
| `postgres reset`    | Drop + create + sync                                          |
| `postgres wait`     | Wait for DB readiness                                         |
| `postgres diagnose` | Health checks                                                 |
| `postgres backups`  | Backup subgroup                                               |
