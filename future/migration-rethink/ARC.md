# Migration rethink

Replace Django's migration system with two complementary systems: **migrations** for imperative schema changes that code depends on, and **schema convergence** for declarative state (indexes, constraints, NOT NULL) that the framework applies automatically using online-safe Postgres patterns.

The current system bundles everything into migration files — schema changes, index creation, constraint management, dependency graphs — and wraps it all in transactions that hold dangerous locks. The rethink separates what _must_ be imperative (adding/removing columns, data operations) from what can be _declarative_ (the database should match the model definitions), and handles each appropriately.

## How this compares

> Some rows describe the target vision (flat timestamps, thin operations, fresh DB from models), not necessarily the current implementation. See [Implementation status](#implementation-status) for what's done.

|                               | **Plain**                                                 | **Rails**                           | **Laravel**                   | **Ecto**                        | **Prisma**                                      | **Django**                                    |
| ----------------------------- | --------------------------------------------------------- | ----------------------------------- | ----------------------------- | ------------------------------- | ----------------------------------------------- | --------------------------------------------- |
| **Migration authoring**       | Auto-detected from models                                 | Manual (developer writes DSL)       | Manual (developer writes DSL) | Manual (developer writes DSL)   | Auto-detected from schema file                  | Auto-detected from models                     |
| **Index/constraint handling** | Declarative on model, applied automatically with safe DDL | Manual migrations (+ safety gems)   | Manual migrations             | Manual migrations               | Declarative in schema, but no safe DDL patterns | Manual migrations (+ third-party safety libs) |
| **Safe DDL built in?**        | Yes (CONCURRENTLY, NOT VALID, CHECK-then-NOT-NULL)        | No (strong_migrations gem)          | No (manual)                   | No (manual)                     | No                                              | No (django-pg-zero-downtime-migrations)       |
| **Failure model**             | Migrations: batch rollback. Convergence: per-op retry.    | Per-migration, reversible in theory | Per-batch, reversible         | Per-migration, explicit up/down | Forward-only                                    | Per-migration, reversible in theory           |
| **Reverse migrations**        | No (forward-only, fix-forward)                            | Yes (often broken)                  | Yes (often untested)          | Yes (explicit down)             | No                                              | Yes (often broken)                            |

Rails, Laravel, and Ecto all require developers to manually write every migration, including indexes and constraints. Django and Prisma auto-detect changes but still put indexes/constraints in migration files. Plain is the only system that separates declarative schema (auto-applied) from imperative changes (migration files).

## Arguments against this design

**"Two systems is more complex than one."**

_Counter:_ Django's "one system" is deceptively complex — ModelState, ProjectState, operation classes, the dependency graph, the autodetector, the schema editor's DDL translation layer, squash/merge machinery. That's ~5,000+ lines of the hardest code in the framework. The two-system design is conceptually simpler (imperative vs declarative) even if it has more named components. Developers never think about convergence — they declare indexes on models and `postgres sync` handles it.

**"Auto-applying schema changes during deploy is scary."**

_Counter:_ Convergence uses CONCURRENTLY (doesn't block writes), lock_timeout (fails fast if it can't acquire a lock), and the backfill threshold (reports instead of acting on large tables). The scary alternative is developers forgetting to use CONCURRENTLY and taking the site down with a regular CREATE INDEX.

**"No reverse migrations means harder incident recovery."**

_Counter:_ Reverse migrations were already unreliable — most are untested. The real incident recovery is rolling back the code deploy (old code + forward-compatible schema is the expand-and-contract guarantee). Pretending the framework can safely automate reversal gives false confidence.

---

## Remaining vision

What's done is documented in the README. What's still aspirational:

- **Safe by default.** `lock_timeout` on all DDL. Advisory locks for migration coordination. No expert knowledge required.
- **Fresh databases don't need schema history.** `postgres sync` on an empty database creates everything from model definitions — no migration replay. Depends on migration format work.
- **Migrations are even simpler.** Flat timestamped list, no per-app directories, no dependency graph. No no-op migrations for `choices`, `validators`, `on_delete`, etc.

## Implementation status

The original plan had four sequential phases. In practice, we collapsed Phases 2 and 3 — moving features from migrations to convergence incrementally rather than shipping convergence as opt-in first. The migration system's constraint/index operations were removed entirely, not deprecated.

The migration format changes (thin operations, flat timestamps) are deferred indefinitely. The strategy is to keep expanding convergence using the existing Django-derived migration format and see how far that gets us. As convergence takes over indexes, constraints, NOT NULL, defaults, and FKs, migrations naturally get simpler without requiring a format overhaul.

### Done: Convergence core

Indexes and constraints are fully managed by convergence. The migration autodetector no longer generates operations for them, and the operation classes (AddConstraint, RemoveConstraint, AddIndex, RemoveIndex, RenameIndex) have been removed.

- [x] `postgres schema` comparison engine — check, unique, FK constraint + INVALID index detection
- [x] `postgres converge` — constraints (NOT VALID + VALIDATE, USING INDEX) and indexes (CONCURRENTLY)
- [x] Removed constraint/index operations from migration system and all existing migration files
- [x] `postgres sync` = `migrations create` (DEBUG) + `migrations apply` + `converge`
- [x] Pass ordering (rebuild invalid → create indexes → add constraints → validate → drop constraints → drop indexes)
- [x] INVALID index detection + rebuild
- [x] Per-operation commits with rollback on failure
- [x] Test DB setup runs convergence after migrations
- [x] Dev server uses `postgres sync`
- [x] CLI: `migrations create` (was `makemigrations`), removed `plain migrate` shortcut

### Done: Convergence expansion

- [x] Move FK constraints from field-level migration operations to convergence
- [x] NOT NULL convergence (CHECK NOT VALID + VALIDATE + SET NOT NULL)
- [x] Removed dead FK constraint, index, and deferred SQL infrastructure from schema editor

### Remaining: Convergence expansion

- [ ] Defaults convergence (SET DEFAULT / DROP DEFAULT)
- [ ] Remove historical model reconstruction from RunPython — change signature to `(schema_editor,)`, use real imports instead of reconstructed state. Once nothing consumes ProjectState, stop generating migrations for `choices`, `validators`, `default` (non-db), `on_delete`, `related_name`, `ordering`

### Remaining: Safety

Standalone improvements to the migration/convergence system.

- [ ] [lock-timeout-default](lock-timeout-default.md) — `SET lock_timeout` on DDL
- [ ] [advisory-locks](advisory-locks.md) — session-level advisory lock for migration coordination
- [ ] [failure-handling](failure-handling.md) — batch transaction for migrations, per-operation for convergence

### Deferred: Migration format

These are possible future improvements but not actively planned. The existing Django-derived migration format works fine — as convergence takes over more responsibilities, migrations naturally get simpler without requiring a format change. We'll see where convergence expansion gets us before deciding if any of this is worth doing.

- [ ] [thin-operations](thin-operations.md) — new migration format (thin operation classes, boundary enforcement)
- [ ] [flat-timestamps](flat-timestamps.md) — single directory, timestamp-based, new tracking table
- [ ] Schema editor refactor — SQL generation into Index/Constraint classes

### Deferred: Benefits that require migration format changes

These depend on the migration format work above. They are follow-on optimizations, not required to prove the main rethink.

- [ ] [fresh-db-from-models](fresh-db-from-models.md) — fast test setup, no migration replay
- [ ] [generated-baseline](generated-baseline.md) — optional release artifact for fresh installs and upgrade support windows
- [ ] [remove-squash](remove-squash.md) — no longer needed once fresh-db-from-models exists
- [ ] DB-free `--check` via operation replay
- [ ] `--replay` CI verification (migration history matches models)

## Key design decisions

### Why convergence works for indexes/constraints but not columns

The split comes down to **what the code depends on.** A missing column means a hard crash. A missing secondary index means slower queries. Constraints sit between those extremes: declarative like indexes, but correctness-critical like schema shape.

We considered making AddColumn and CreateTable convergence-managed too (they're unambiguous). But data migrations that backfill a new column must run AFTER the column exists. With migrations, this is natural — both are in the batch transaction, timestamp-ordered. With convergence, you'd need structural convergence → data migrations → schema convergence — three phases instead of two. The current two-phase design (migrations → convergence) is simpler.

### Rollback story

Normal `postgres sync` only adds and validates declared state — it never auto-drops undeclared objects. Cleanup is explicit via `--drop-undeclared`. This keeps rollback boring: roll back the code, leave additive schema in place, clean up explicitly when ready.

### No no-op migrations

Only DB-relevant changes should produce migrations. Changing `choices`, `validators`, `default` (non-db), `on_delete`, `related_name`, `ordering`, etc. should NOT generate a migration. Not fully implemented yet — requires removing historical model reconstruction from RunPython (see [Remaining: Convergence expansion](#remaining-convergence-expansion)).

## Industry context

- **Rails**: `schema.rb` as authoritative snapshot, migrations deletable, `db:schema:load` for fresh DBs. No convergence — but the schema file serves a similar "truth is in the model, not the history" role. The safety ecosystem (strong_migrations, safe-pg-migrations, pg_ha_migrations) provides the safe DDL patterns that convergence bakes in by default.
- **Laravel**: `schema:dump` captures schema + migration records as SQL. Fresh DBs load dump then run post-dump migrations. `--prune` deletes old files.
- **Ecto**: `structure.sql` dump, automatic/manual migration directories for deploy ordering, advisory locks (v3.9+). Jose Valim rejected built-in squash in favor of dump+load.
- **Prisma**: Declarative schema file, auto-generated migration diffs, no data migration support. `db push` for prototyping (applies schema directly without migrations). No safe DDL patterns and no auto-backfill — adding a required column to a populated table simply fails.
- **Atlas** (Go): Declarative schema-as-code with diff-based migration planning. Closest to convergence in philosophy — diffs desired state against actual DB. Uses plan structure (not a dependency graph) to order operations, with concurrent index creation before constraint attachment. 50+ safety analyzers. Does not auto-backfill.
- **pgroll** (Xata): Expand/contract pattern for zero-downtime Postgres migrations. Batched backfills (1,000 rows default, configurable) with inter-batch delay. Manages dual-schema access during migration lifecycle — more complex than convergence needs.

None of these combine declarative convergence with imperative migrations the way this design does. Atlas is the closest parallel for the declarative side but doesn't separate convergence from migrations — everything goes through its plan engine. The Rails safety gems prove the individual patterns work at scale but require manual orchestration that convergence automates.

## Future direction

The obvious next step beyond `--prune` is a deploy-aware rollout model where Plain can automate contraction after cutover/rollback windows rather than relying on an explicit contraction command. That is intentionally out of scope for the current rethink. See deploy-aware-rollouts.md.

## What this replaced

- `migrations-safety-analysis` future → convergence uses safe patterns by default
- `models-non-blocking-ddl` future → the convergence engine implements all non-blocking DDL patterns
- `fk-auto-index-removal` arc → convergence manages all indexes from model declarations
