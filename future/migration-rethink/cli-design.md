# CLI design

> **Note:** This design doc predates the implementation. The actual CLI uses `migrations create` (not `schema --make`) for migration generation, and `postgres sync` runs `migrations create` in DEBUG mode. `postgres converge` exists as a standalone subcommand. See the current CLI via `plain --help` and `plain postgres --help`.

**This is the authoritative CLI reference.** sync-command.md covers the sync behavior/semantics in depth; this doc defines the actual command surface.

Everything under `plain postgres`. No top-level shortcuts.

Two primary commands: `schema` (understand your database) and `sync` (update your database). Everything else is infrastructure or diagnostics.

## The dev loop

```bash
# Edit model...
plain postgres sync              # in DEBUG: generate migrations, apply, converge
```

Or explicitly:

```bash
plain postgres schema            # see what's different
plain migrations create          # generate migration files
plain postgres sync              # apply everything
```

The dev server could also detect unmigrated model changes and show a warning — similar to Django's "You have unapplied migrations" but earlier: "Model changes detected. Run `plain postgres sync` or `plain migrations create`."

## The deploy

```bash
plain postgres sync
```

**In production, `postgres sync` never generates migration files.** It only applies existing migrations and converges schema. The DEBUG-only auto-create behavior is a local development convenience, not part of the deploy contract.

For contraction/removal deploys:

```bash
plain postgres sync --prune
```

That should be the minority case. Most deploys are ordinary `sync`; `--prune` is only for intentional removal of convergence-owned objects.

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

Internally: apply pending migrations (batch transaction) → required convergence for defaults/constraints/NOT NULL → best-effort performance convergence for secondary indexes → report any cleanup available via `--prune`. The user just sees one operation.

On an empty database, creates everything from model definitions, converges the declared schema, then marks all migrations as applied. App seeding/init is separate and out of scope here. See fresh-db-from-models.md for the full design.

Handles stale migration records automatically. If performance convergence partially failed, run again to retry.

As a production pre-deploy command, `postgres sync` should have a strict contract:

- Migration failure rolls back the batch and aborts the deploy.
- Required correctness convergence failure aborts the deploy, but already-applied safe convergence work remains committed.
- Performance convergence failure warns and retries later.
- Cleanup and destructive contraction do not run in ordinary `sync`; they require `--prune`.

That yields two explicit deploy modes:

- `plain postgres sync` for ordinary additive/tightening deploys
- `plain postgres sync --prune` for contraction deploys

The important point is that `--prune` is not a routine extra step the deployer must remember on every rollout. It is the explicit marker for the smaller class of deploys that actually remove declarative schema objects.

Correctness convergence failures are actionable — every failure tells you exactly what to do:

```
$ plain postgres sync

Schema:
  ✗ orders.status — NOT NULL cannot be applied
    2,000,000 rows have NULLs, model has default 'active'
    Exceeds auto-backfill threshold (2,000,000 > 100,000)
    Run: plain postgres backfill orders.status --batch-size 10000

  ✗ orders.legacy_ref — NOT NULL cannot be applied
    1,200 rows have NULLs, no model default
    Write a data migration to populate this column:
    Run: plain migrations create --empty --name backfill_legacy_ref
```

**Flags:**

- `--check` — exit non-zero if anything is pending (for CI: "is the DB fully in sync?")
- `--dry-run` — show the full plan with exact SQL, lock levels, and estimated impact (see below)
- `--prune` — include explicit cleanup/contraction work for undeclared convergence-owned objects
- `--replay` — apply all migrations from scratch on an empty DB, then verify the result matches model definitions. Catches divergence between migration history and models. For CI — see below.
- `--fake <timestamp>` — mark a migration as applied without running it (escape hatch)
- `--json` — machine-readable output for CI pipelines and monitoring

### `--dry-run` plan output

`postgres sync --dry-run` shows exactly what will execute, in order, with lock levels:

```
$ plain postgres sync --dry-run

Migrations (batch transaction):
  20240315_110000 add_status_to_orders
    AddColumn("orders", "status", "varchar(50) NULL")
    → ALTER TABLE orders ADD COLUMN status varchar(50) NULL;

Schema convergence:
  Pass 0: SET DEFAULT 'active' ON orders.status
          catalog-only, <1ms, ACCESS EXCLUSIVE (brief)
  Pass 1: CREATE INDEX CONCURRENTLY orders_status_idx ON orders (status)
          ~1,247 rows, SHARE UPDATE EXCLUSIVE
  Pass 2: ADD CONSTRAINT orders_author_fk FOREIGN KEY ... NOT VALID
          <1ms, SHARE ROW EXCLUSIVE
  Pass 3: VALIDATE CONSTRAINT orders_author_fk
          ~1,247 rows, SHARE UPDATE EXCLUSIVE
  Pass 4: SET NOT NULL ON orders.status
          <1ms (scan skipped by CHECK), ACCESS EXCLUSIVE (brief)

No blockers. Safe to run.
```

This is what operators review before running in production.

For contraction deploys, `--dry-run` should also show the prune plan explicitly:

```
$ plain postgres sync --prune --dry-run

Cleanup:
  Drop constraint orders_old_unique
  Drop index orders_legacy_idx
```

### `--replay` migration verification

Test databases use fresh-db-from-models (fast). Production databases are built by applying migrations incrementally over time. These are two different code paths to the same destination. `--replay` verifies they produce the same result:

```
$ plain postgres sync --replay

Creating temporary database...
Applying 47 migrations in order...
Running convergence...
Comparing result against model definitions...
✓ Schema matches models. Migration history is consistent.
```

If migrations have diverged from models (a migration was edited after being applied, a model was changed without a migration, etc.), `--replay` catches it. Recommended as a CI step.

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

Run `plain migrations create` to create a migration.
Run `plain postgres sync` to apply all changes.
```

**Arguments:**

- `<ModelName>` — show one model (accepts model name, qualified name, or table name)
- No argument — summary of all models

**Flags:**

- `--check` — exit non-zero if any differences (for CI: "are there unmigrated model changes?")
- `--sql` — show the DDL that would be executed

Migration generation lives on `plain migrations create`. Older drafts put this on `schema --make`, but the current split is clearer:

- `plain postgres schema` — inspect
- `plain migrations create` — write migration files
- `plain postgres sync` — apply migrations + convergence

### Migration warnings

`plain migrations create` warns about dangerous operations before writing the file:

```
$ plain migrations create

⚠ RemoveColumn: orders.legacy_email — permanently deletes data
⚠ AlterColumnType: orders.amount text → integer — may lose data, add using= parameter

Generated: app/migrations/20240315_110000_alter_orders.py
```

Because migrations use thin operations (not raw SQL), the framework knows exactly what each migration does. Warnings are structural, not pattern-matched:

- **RemoveColumn / RemoveTable** — data loss
- **AlterColumnType** with narrowing cast — may fail or truncate
- **RunSQL** — escape hatch, flagged for review ("this migration contains raw SQL that bypasses the operation layer")

The operation set itself enforces the migration/convergence boundary — there is no `CreateIndex` or `SetNotNull` operation. No SQL linting needed for boundary violations.

### Convergence hazards

`postgres sync` warns about convergence hazards at apply time:

```
$ plain postgres sync

Schema convergence:
  ⚠ INDEX_BUILD: CREATE INDEX CONCURRENTLY orders_status_idx
    ~2,000,000 rows — CPU-intensive, may take several minutes
  ⚠ DELETES_DATA: DROP INDEX CONCURRENTLY orders_legacy_idx (--prune)

  Allow these hazards? [y/n]
  Or: plain postgres sync --allow-hazards INDEX_BUILD,DELETES_DATA
```

Inspired by [pg-schema-diff](https://github.com/stripe/pg-schema-diff)'s hazard system (production-tested at Stripe): dangerous operations require explicit acknowledgment. In CI/deploy scripts, use `--allow-hazards` to pre-approve specific hazard types. Without it, sync pauses for confirmation on any hazardous operation.

Migration warnings gate at generation time (before commit). Convergence hazards gate at apply time (before execution).

`--prune` fits this same philosophy: contraction is allowed, but it should be explicit in the command and visible in the dry-run/hazard output.

### Why keep `migrations create` as a separate command?

The implementation ended up with an explicit `plain migrations create` command rather than `postgres schema --make`. That is a better fit for the current workflow:

- `plain postgres sync` can auto-run `migrations create` in DEBUG for fast local iteration.
- Production `plain postgres sync` never writes files.
- The explicit command still exists for review, naming, and CI checks.

**How other frameworks handle the "generate migration" verb:**

| Framework | Command                             | Pattern                                                                       |
| --------- | ----------------------------------- | ----------------------------------------------------------------------------- |
| Rails     | `rails generate migration <name>`   | Explicit top-level command. Manual — generates a stub, developer fills it in. |
| Laravel   | `php artisan make:migration <name>` | Explicit top-level command. Same manual stub pattern as Rails.                |
| Ecto      | `mix ecto.gen.migration <name>`     | Explicit top-level command. Manual stub.                                      |
| Django    | `python manage.py makemigrations`   | Explicit top-level command. Auto-detects changes from models.                 |
| Prisma    | `prisma migrate dev`                | Part of the dev workflow — auto-generates as a side effect.                   |
| Atlas     | `atlas migrate diff <name>`         | Explicit command. Auto-detects changes from schema definition.                |

Plain's `migrations create` is still auto-detected from models like Django and Atlas — there's no manual stub to fill in for schema changes. The difference is just command surface: generation is explicit, while `sync` can wrap it in development.

**Decision: `migrations create` plus DEBUG `sync` convenience is sufficient.** It keeps file generation explicit in review/CI workflows without making local dev verbose.

### Two `--check` modes

Both useful in CI, checking different things:

- `migrations create --check` — "would current model changes generate a migration file?" This is the code-state check.
- `postgres sync --check` — "are there pending migrations or convergence work?" Requires a database (introspects actual state).

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

## Observability

### Structured output

`--json` on `sync` and `schema` produces machine-readable output for CI pipelines and monitoring:

```json
{
  "migrations": [
    {"timestamp": "20240315_110000", "name": "add_status_to_orders", "status": "applied", "duration_ms": 12}
  ],
  "convergence": [
    {"table": "orders", "operation": "create_index", "name": "orders_status_idx", "status": "applied", "duration_ms": 847},
    {"table": "orders", "operation": "not_null", "column": "status", "status": "blocked", "reason": "47 NULLs, has default"}
  ],
  "blockers": 1,
  "total_duration_ms": 1203
}
```

### Exit codes

| Code | Meaning                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------ |
| 0    | Success — required state applied; any remaining work is best-effort/performance only                   |
| 0    | Nothing to do — already in sync                                                                        |
| 1    | Migration failure — batch rolled back                                                                  |
| 2    | Required convergence failure — migrations applied but declared correctness state was not fully reached |

Code 2 is a deploy failure. The models declared a constraint/default contract that the database did not reach. Performance-only convergence warnings still exit 0 unless `--check` is used.

### Timing

Every operation reports its duration. `postgres sync` prints a summary:

```
Completed in 2.1s (migrations: 0.1s, convergence: 2.0s)
  Slowest: CREATE INDEX CONCURRENTLY orders_status_idx (1.8s)
```

## Migration directory integrity

A `migrations.sum` file (similar to Atlas's `atlas.sum`) records a hash of the migration directory contents. This catches:

- Migrations modified after being applied to any database
- Migrations deleted without proper cleanup
- Migrations reordered or renamed

`postgres sync` verifies the checksum before running. If it doesn't match, sync refuses with a clear error. `migrations create` updates the checksum when generating a new migration.

This is cheap to implement (SHA-256 of sorted filenames + contents) and high value for trust — it guarantees the migration files in the repo are the same ones that were tested in CI.

## Preflight integration

`plain check` includes:

- `migrations create --check` — unmigrated model changes
- `postgres sync --check` — pending sync work

`plain check --skip-db` to skip when no DB is available.

## What's removed

| Gone                      | Replaced by                                         |
| ------------------------- | --------------------------------------------------- |
| `plain migrate`           | `postgres sync`                                     |
| `plain makemigrations`    | `plain migrations create`                           |
| `migrations list`         | `postgres schema` (shows pending), `sync --dry-run` |
| `migrations squash`       | Not needed                                          |
| `migrations apply`        | `postgres sync`                                     |
| `migrations apply --fake` | `postgres sync --fake`                              |
| `migrations prune`        | `postgres sync --prune`                             |
| `drop-unknown-tables`     | `postgres diagnose` can report                      |

`postgres sync` is the happy-path write command, but lower-level commands still exist. `migrations create` is for explicit review, `migrations apply` is a low-level escape hatch/admin tool, and `postgres converge` remains useful for retries and repair. The important product decision is not "one binary entry point only"; it's that ordinary users can rely on `postgres sync` as the main workflow.

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
