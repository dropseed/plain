# Fresh database from models

> **Status: Deferred optional optimization.** This is not required for the core rethink. It depends on migration format changes that are not actively planned. Application seeding/init is explicitly out of scope here — this doc only covers schema lifecycle and incremental historical migrations.

## Problem

Today, setting up a fresh database requires replaying every migration from the beginning. As migration history grows, this gets slower and more fragile. Rails/Laravel/Ecto solve this with schema dump files that capture the current state.

With schema convergence, Plain has a better option: generate DDL directly from model definitions. No dump file, no migration replay. The models _are_ the schema.

## How it works

When `postgres sync` runs against an empty database:

1. Introspect all registered models
2. Generate `CREATE TABLE` statements with all columns, types, NOT NULL, and defaults (same DDL as CreateModel in a migration — see slim-migrations.md)
3. Execute them in any order (no ordering issues — FK constraints come from convergence, not DDL)
4. Run required convergence to add defaults, FK constraints, CHECK constraints, unique constraints, and NOT NULL where declared
5. Mark all migration files as applied

This deliberately keeps fresh-db setup schema-only. Historical data operations are incremental concerns; they do not replay on a fresh database built from current models.

Step 5 prevents schema migrations from trying to re-apply changes already reflected in the DDL, and prevents historical backfills from running against a schema they were never meant to target.

## Historical data operations on fresh databases

**Fresh databases do not replay historical data migrations.**

Once schema migrations are skipped and eventually deleted, old `run()` operations are no longer running against the schema they were written for. A rename that is harmless on an existing database can break fresh setup if an old backfill still references the old table or column name.

So the fresh-db contract is intentionally narrow:

- **Schema history** is collapsed into current model-derived DDL plus convergence.
- **Historical data migrations** are incremental-only. They exist to move already-populated databases forward.
- **Application seeding/init** is a separate concern and is out of scope for this design.

That keeps fresh setup deterministic without trying to make migration history recreate the full application data state.

### How other frameworks handle this

- **Rails**: `db/seeds.rb` runs via `db:seed`, called automatically by `db:setup` and `db:prepare`. Seeds are separate from schema history. The `db:migrate` vs `db:setup` split means fresh databases and incremental updates take different code paths, which diverge over time.

- **Laravel**: Seeder classes in `database/seeders/`, run via `db:seed`. `migrate:fresh --seed` drops all tables, re-runs migrations, then seeds. Seeds are completely separate from migrations.

- **Ecto/Phoenix**: `priv/repo/seeds.exs` is a plain Elixir script. `mix ecto.setup` runs `ecto.create`, `ecto.migrate`, then `run priv/repo/seeds.exs` in sequence. Clean and explicit, but separate from migration history.

- **Django**: No built-in seed mechanism. Data migrations via RunPython are the recommended approach for initial data. `loaddata` with fixtures exists but is manual and not integrated into the migration pipeline. Django replays against historical schema state, which is exactly what Plain is trying to avoid for fresh DB speed.

- **Prisma**: `prisma db seed` configured in `prisma.config.ts`. Prisma v7 removed automatic seeding from `migrate dev` and `migrate reset` — seeds must be run explicitly. No data migration support at all; seed scripts are completely outside the migration system.

- **Atlas**: Declarative data management (Pro feature) with INSERT/UPSERT/SYNC modes for lookup tables and reference data. The important lesson is that schema lifecycle and app data lifecycle are different concerns.

The pattern is clear: schema setup and app data setup are usually separate. This doc is intentionally only solving the schema side.

## Test databases

Test database creation uses the same `postgres sync` code path as production fresh-db-from-models. No special test machinery needed:

1. Create empty test database
2. `postgres sync` detects empty DB → creates tables from models, applies required convergence, optionally applies performance convergence, marks all migrations as applied
3. Tests run against the schema-correct database

This is dramatically faster than the current approach of replaying every migration from the beginning. For a project with 100+ migrations, fresh-from-models takes seconds instead of minutes. And it's always correct — the test schema matches the current models exactly, no accumulated migration drift.

## Benefits

- **No schema dump file to maintain.** Rails needs `schema.rb` regenerated on every migrate. Laravel needs `schema:dump` run periodically. Plain just reads the models.
- **Always current.** The dump file can go stale if someone forgets to regenerate it. Models are always the truth.
- **Fast CI/test setup.** Test databases are created from models + dev-mode convergence. No migration replay.
- **Schema migration files are deletable.** Migrations with `operations` serve no purpose once all existing databases have applied them. Backfill migrations are also deletable once every database has run them.
- **One code path for fresh and incremental.** `postgres sync` does the right thing regardless of whether the database is empty or has history.

## Possible follow-on: generated baseline artifact

If Plain later needs a stronger fresh-install contract for self-hosted releases, it can generate a checked-in baseline SQL artifact **from the models** at release time rather than regenerating the schema dynamically on every fresh install.

That would keep models as the source of truth while freezing the exact DDL for a release. Fresh installs would load the baseline, then converge. Existing databases would still use normal incremental migrations plus convergence.

This is not required for the core rethink. It is a possible follow-on if support-window policy, reviewable release DDL, or future DB-native objects (views, triggers, functions, extensions) make a checked-in artifact more attractive. See [generated-baseline](generated-baseline.md).

## What this replaces

- `schema:dump` / `schema:load` (Laravel)
- `schema.rb` / `db:schema:load` (Rails)
- `ecto.dump` / `ecto.load` (Ecto)
- The `migrations squash` command — no longer needed
- The `migrations reset` skill — trivially simple now

## Considerations

- Table creation order: with FK constraints in convergence, tables can be created in any order. No circular dependency issues.
- The `CreateModel` DDL generation already exists in the schema editor — this reuses it.
- Historical data migrations are incremental-only and are not part of fresh setup. If an application needs seed/init data, that belongs to a separate app-level mechanism.
- Migration files that contain only schema operations (no RunPython/RunSQL) are truly inert on fresh databases — they get marked as applied and nothing executes. These are the ones that are safely deletable.
