# Fresh database from models

## Problem

Today, setting up a fresh database requires replaying every migration from the beginning. As migration history grows, this gets slower and more fragile. Rails/Laravel/Ecto solve this with schema dump files that capture the current state.

With schema convergence, Plain has a better option: generate DDL directly from model definitions. No dump file, no migration replay. The models _are_ the schema.

## How it works

When `postgres sync` runs against an empty database:

1. Introspect all registered models
2. Generate `CREATE TABLE` statements with all columns, types, NOT NULL, and defaults (same DDL as CreateModel in a migration — see slim-migrations.md)
3. Execute them in any order (no ordering issues — FK constraints come from convergence, not DDL)
4. Run convergence to add indexes, FK constraints, CHECK constraints, unique constraints
5. Replay data migrations — `.py` files with `run()` execute in timestamp order. Schema migrations (files with `operations`) are skipped since the schema already exists from model-based DDL.
6. Mark all migration files as applied

Step 5 is the key decision. A fresh database built from models is not truly migration-free — it still reads migration files and selectively executes data operations. This is correct because some RunPython migrations insert seed data (permission records, default config rows, lookup tables) that the application requires to function. Skipping them would leave a fresh database in a broken state.

Step 6 prevents schema migrations from trying to re-apply changes already reflected in the DDL.

## RunPython on fresh databases: the decision

**All RunPython/RunSQL operations run on fresh databases. No distinction between "seed" and "backfill."**

This is the simplest correct approach. The alternatives — a `run_on_fresh` flag, a separate seed mechanism, or skipping everything — all add complexity without sufficient benefit:

- A flag requires developers to classify every data migration at write time, and getting it wrong silently breaks fresh databases or wastes time running irrelevant backfills.
- A separate seed mechanism splits data operations across two systems, which means two things to maintain, two things that can go stale, and two things to coordinate during deploys.
- Skipping everything breaks fresh databases that need seed data to function.

Running all data operations is safe because: backfill migrations that touch existing data are no-ops on empty tables (there's nothing to backfill), and seed migrations that insert required data do exactly what's needed. The cost is negligible — a handful of no-op RunPython calls on empty tables add milliseconds to fresh setup.

### How other frameworks handle this

Every major framework that has a seed mechanism keeps it **separate from migrations** — and every one of them has pain points from that separation:

- **Rails**: `db/seeds.rb` runs via `db:seed`, called automatically by `db:setup` and `db:prepare`. Seeds are not versioned or ordered — the entire file re-runs each time. Developers constantly struggle with idempotency (seeds that crash on re-run because records already exist). The `db:migrate` vs `db:setup` split means fresh databases and incremental updates take different code paths, which diverge over time.

- **Laravel**: Seeder classes in `database/seeders/`, run via `db:seed`. `migrate:fresh --seed` drops all tables, re-runs migrations, then seeds. Seeds are completely separate from migrations — no ordering guarantee relative to schema changes. Same idempotency problems as Rails.

- **Ecto/Phoenix**: `priv/repo/seeds.exs` is a plain Elixir script. `mix ecto.setup` runs `ecto.create`, `ecto.migrate`, then `run priv/repo/seeds.exs` in sequence. Clean and explicit, but the seed script uses current model code against a database that was built by replaying historical migrations — version skew is possible.

- **Django**: No built-in seed mechanism. Data migrations via RunPython are the recommended approach for initial data. `loaddata` with fixtures exists but is manual and not integrated into the migration pipeline. The `elidable=True` flag on RunPython marks operations as removable during squash, but there's no "skip on fresh database" flag — all RunPython operations run on all databases.

- **Prisma**: `prisma db seed` configured in `prisma.config.ts`. Prisma v7 removed automatic seeding from `migrate dev` and `migrate reset` — seeds must be run explicitly. No data migration support at all; seed scripts are completely outside the migration system.

- **Atlas**: Declarative data management (Pro feature) with INSERT/UPSERT/SYNC modes for lookup tables and reference data. For the versioned workflow, seed data goes in migration files as INSERT statements — same approach as "RunPython always runs."

The pattern is clear: frameworks that separate seeds from migrations create a two-system coordination problem. Frameworks that keep data operations in migrations (Django, Atlas) avoid this but need all data operations to run on fresh databases. Plain should follow the latter — one system, one code path, no classification burden.

## Test databases

Test database creation uses the same `postgres sync` code path as production fresh-db-from-models. No special test machinery needed:

1. Create empty test database
2. `postgres sync` detects empty DB → creates tables from models, converges (dev mode — skips CONCURRENTLY), replays data operations, marks all applied
3. Tests run against the fully-synced database

This is dramatically faster than the current approach of replaying every migration from the beginning. For a project with 100+ migrations, fresh-from-models takes seconds instead of minutes. And it's always correct — the test schema matches the current models exactly, no accumulated migration drift.

## Benefits

- **No schema dump file to maintain.** Rails needs `schema.rb` regenerated on every migrate. Laravel needs `schema:dump` run periodically. Plain just reads the models.
- **Always current.** The dump file can go stale if someone forgets to regenerate it. Models are always the truth.
- **Fast CI/test setup.** Test databases are created from models + dev-mode convergence. No migration replay.
- **Schema migration files are deletable.** Migrations with `operations` serve no purpose once all existing databases have applied them. Data migrations (with `run()`) persist as long as the data operation is needed for fresh database setup (backfills are typically no-ops on empty tables and can also be deleted; only seed data migrations persist long-term).
- **One code path for fresh and incremental.** `postgres sync` does the right thing regardless of whether the database is empty or has history.

## What this replaces

- `schema:dump` / `schema:load` (Laravel)
- `schema.rb` / `db:schema:load` (Rails)
- `ecto.dump` / `ecto.load` (Ecto)
- The `migrations squash` command — no longer needed
- The `migrations reset` skill — trivially simple now

## Considerations

- Table creation order: with FK constraints in convergence, tables can be created in any order. No circular dependency issues.
- The `CreateModel` DDL generation already exists in the schema editor — this reuses it.
- RunPython operations that import models work because models are current code, not historical state. This is already the design choice in the migration rethink (no ModelState/ProjectState reconstruction).
- Migration files that contain only schema operations (no RunPython/RunSQL) are truly inert on fresh databases — they get marked as applied and nothing executes. These are the ones that are safely deletable.
