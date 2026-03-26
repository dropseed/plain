# Sync behavior and semantics

How `postgres sync` works internally. For the CLI surface (flags, output format, full command list), see cli-design.md.

## What sync does

`postgres sync` brings a database in line with the current code. One command, two modes depending on database state.

### On an existing database (incremental)

1. **Acquire advisory lock** — serialize against concurrent sync runs (multi-node deploy)
2. **Apply pending migrations** — in timestamp order, batch transaction (all-or-nothing). Schema operations (AddField, CreateModel) and data operations (RunPython, RunSQL) run together.
3. **Backfill NULLs** — for columns where the model declares NOT NULL with a default and the DB has NULLs, backfill in batches before convergence attempts the constraint
4. **Converge schema** — indexes, constraints, NOT NULL, using safe Postgres patterns. Per-operation, non-transactional. Failures don't block other operations.
5. **Report pending work** — anything convergence couldn't do (e.g., NOT NULL blocked by NULLs with no model default)

### On a fresh database (empty, no tables)

1. **Generate DDL from model definitions** — `CREATE TABLE` for all registered models, with columns, types, and defaults
2. **Run convergence** — indexes, constraints, NOT NULL
3. **Replay data operations** — RunPython/RunSQL from migration files execute in timestamp order. Schema operations (AddField, CreateModel, etc.) are skipped since the schema already exists from step 1.
4. **Mark all migrations as applied** — prevents re-application on subsequent sync runs

Step 3 is important — fresh databases are not truly migration-free. Data operations (seed data, lookup table inserts, permission records) must run for the application to function. See fresh-db-from-models.md for the full rationale and industry comparison.

## Idempotency

`postgres sync` is safe to run repeatedly:

- Migrations already applied are skipped (tracked in DB)
- Convergence compares desired vs actual — already-correct objects are skipped
- INVALID indexes from failed CONCURRENTLY builds are detected, dropped, and retried
- Partially converged state (3 of 5 indexes created, then failure) converges the remaining 2 on next run

## Advisory lock coordination

Multiple sync processes (e.g., during a rolling deploy) are serialized by a Postgres advisory lock. The migration phase is fully serialized — only one process applies migrations. Convergence uses a separate advisory lock key to avoid blocking migration application while convergence runs.

If a sync process crashes while holding the lock, the lock is released automatically (session-level advisory lock). No manual intervention needed.

## The batch transaction for migrations

All pending migrations run in a single transaction. If any migration fails, all roll back. This works because slim migrations are catalog-only DDL (fast, no long locks) plus data operations. No CONCURRENTLY or NOT VALID operations in migrations — those are convergence concerns.

This is a deliberate tradeoff: you can't have a partially-applied migration set. Either all pending migrations apply or none do. This eliminates the "stuck between migrations" state that plagues Django deployments with `atomic=False`.

## Convergence ordering

Convergence uses a fixed five-pass execution order. Some operations have hard ordering requirements (unique constraints need their index built first, NOT NULL needs a validated CHECK to skip the table scan). See schema-convergence.md "Convergence ordering" for the full pass breakdown and lock budget.

## Considerations

- Should `postgres sync` be the default action of `plain postgres` with no subcommand? (Probably not — accidental writes are worse than an extra word.)
- Should `plain check` (preflight) include a `postgres sync --check`? (Yes — see cli-design.md preflight integration.)
