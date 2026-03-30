# Migration rethink

Replace Django's migration system with two complementary systems: **migrations** for imperative schema changes that code depends on, and **schema convergence** for declarative state (indexes, constraints, NOT NULL) that the framework applies automatically using online-safe Postgres patterns.

The current system bundles everything into migration files — schema changes, index creation, constraint management, dependency graphs — and wraps it all in transactions that hold dangerous locks. The rethink separates what _must_ be imperative (adding/removing columns, data operations) from what can be _declarative_ (the database should match the model definitions), and handles each appropriately.

## How it works (draft docs)

Plain manages your database with two systems: **migrations** for structural changes (tables and columns) and **schema convergence** for everything else (indexes, constraints, NOT NULL). One command runs both.

### The dev loop

```bash
# Edit your model, then:
plain migrations create && plain postgres sync   # generate migration + apply everything
```

Or step by step:

```bash
plain postgres schema            # see what changed
plain migrations create          # generate a migration
plain postgres sync              # apply everything
```

### Migrations

Migrations handle adding tables, columns, and renaming things. They use thin operation classes, auto-generated from the diff between your models and the database.

```python
@postgres.register_model
class Order(postgres.Model):
    title: str = types.CharField(max_length=255)
    status: str = types.CharField(max_length=50)
```

```
$ plain migrations create
Created: app/migrations/20240315_110000_add_status_to_orders.py
```

```python
# app/migrations/20240315_110000_add_status_to_orders.py
from plain.postgres.migrations import AddColumn

class Migration:
    operations = [
        AddColumn("orders", "status", "varchar(50) NULL"),
    ]
```

Each operation maps to exactly one SQL statement. There's no `CreateIndex` or `SetNotNull` operation — those are convergence concerns. The boundary is enforced by the API, not by convention.

Migrations run in a single transaction — all pending migrations succeed together or all roll back. No partial state. Generated migrations are expected to be atomic-only; any future escape hatch for bespoke non-atomic work is outside the normal `postgres sync` contract.

For data operations, create a `.py` migration with `--empty`. You can use the ORM — models are imported directly, no historical reconstruction:

```python
# app/migrations/20240320_090000_backfill_status.py
class Migration:
    def run(self, connection):
        from app.models import Order
        Order.query.filter(status=None).update(status="active")
```

### Schema convergence

Indexes, constraints, and NOT NULL are declared on your models. The framework applies them automatically using online-safe Postgres DDL patterns — you never write migrations for these.

```python
@postgres.register_model
class Order(postgres.Model):
    title: str = types.CharField(max_length=255)
    status: str = types.CharField(max_length=50)
    author: User = types.ForeignKeyField(User, on_delete=postgres.CASCADE)

    model_options = postgres.Options(
        indexes=[
            postgres.Index(name="orders_status_idx", fields=["status"]),
            postgres.Index(name="orders_author_id_idx", fields=["author"]),
        ],
        constraints=[
            postgres.UniqueConstraint(name="orders_title_unique", fields=["title"]),
        ],
    )
```

`postgres sync` compares these declarations against the database and applies the difference:

```
$ plain postgres sync

Migrations:
  ✓ 20240315_110000 add_status_to_orders

Schema:
  ✓ orders — created index orders_status_idx
  ✓ orders — created index orders_author_id_idx
  ✓ orders — created FK constraint orders_author_id_fk
  ✓ orders — created unique constraint orders_title_unique
  ✓ orders.status — applied NOT NULL
```

Behind the scenes, convergence uses `CREATE INDEX CONCURRENTLY`, `ADD CONSTRAINT ... NOT VALID` + `VALIDATE`, and the CHECK-then-SET-NOT-NULL pattern. In production, normal `postgres sync` should only do forward, non-destructive convergence work. If required correctness convergence fails, the command exits non-zero, the deploy aborts, and the next run picks up from the partial forward progress already made. Cleanup and contraction stay behind `--prune`.

### Deploying

Preview what will happen:

```
$ plain postgres sync --dry-run

Migrations (batch transaction):
  20240315_110000 add_status_to_orders
    AddColumn("orders", "status", "varchar(50) NULL")
    → ALTER TABLE orders ADD COLUMN status varchar(50) NULL;

Schema convergence:
  Pass 0: SET DEFAULT 'active' ON orders.status (catalog-only, <1ms)
  Pass 1: CREATE INDEX CONCURRENTLY orders_status_idx (SHARE UPDATE EXCLUSIVE)
  Pass 3: VALIDATE CONSTRAINT orders_author_fk (SHARE UPDATE EXCLUSIVE)
  Pass 4: SET NOT NULL ON orders.status (<1ms, scan skipped)

No blockers. Safe to run.
```

Then apply:

```bash
plain postgres sync
```

One command. Applies pending migrations, then converges schema. In production this is the pre-deploy gate: migration failure means rollback and abort; required convergence failure means abort with safe partial forward progress left in place. Idempotent — safe to run any number of times.

### Inspecting

`postgres schema` shows your database state and highlights differences:

```
$ plain postgres schema

orders (4 columns, 1,247 rows, 96 kB)

  Column     Type         Nullable  Default
  ──────────────────────────────────────────
  ✓ id       bigint       NOT NULL  generated
  ✓ title    varchar(255) NOT NULL
  ✓ status   varchar(50)  NOT NULL
  + priority text         NULL                ← not in database

  Indexes:
    ✓ orders_pkey PRIMARY KEY (id)
    ✓ orders_status_idx (status)
    + orders_priority_idx (priority)          ← missing

Run `plain migrations create` to create a migration.
Run `plain postgres sync` to apply all changes.
```

### Fresh databases

`postgres sync` on an empty database creates everything from model definitions — no migration replay needed. Test databases, new environments, and CI all use the same fast path.

### Database branching (Neon, PlanetScale, etc.)

Services like Neon offer instant database branching — copy-on-write forks of your production database for testing. `postgres sync` is a natural fit:

```bash
# CI: create a Neon branch from production, run sync, test
DATABASE_URL=$NEON_BRANCH_URL plain postgres sync
plain test

# Merge PR, apply to production
DATABASE_URL=$PRODUCTION_URL plain postgres sync
```

Convergence is stateless — it doesn't care about the branch's history, just "what do models declare vs what does the DB have." This means `postgres sync` works against any database (production, branch, fresh, stale) without special handling. Migrations merge in git, not at the database level.

### How this compares

|                                       | **Plain**                                                 | **Rails**                           | **Laravel**                   | **Ecto**                        | **Prisma**                                      | **Django**                                    |
| ------------------------------------- | --------------------------------------------------------- | ----------------------------------- | ----------------------------- | ------------------------------- | ----------------------------------------------- | --------------------------------------------- |
| **Migration authoring**               | Auto-detected from models                                 | Manual (developer writes DSL)       | Manual (developer writes DSL) | Manual (developer writes DSL)   | Auto-detected from schema file                  | Auto-detected from models                     |
| **Migration format**                  | Python thin operations (schema), `run()` (data)           | Ruby DSL                            | PHP DSL                       | Elixir DSL                      | `.sql`                                          | Python operations                             |
| **Needs DB to generate?**             | Yes for generation, No for `--check` (replays operations) | No (manual)                         | No (manual)                   | No (manual)                     | Yes (shadow DB)                                 | No (replays state in memory)                  |
| **Index/constraint handling**         | Declarative on model, applied automatically with safe DDL | Manual migrations (+ safety gems)   | Manual migrations             | Manual migrations               | Declarative in schema, but no safe DDL patterns | Manual migrations (+ third-party safety libs) |
| **Safe DDL built in?**                | Yes (CONCURRENTLY, NOT VALID, CHECK-then-NOT-NULL)        | No (strong_migrations gem)          | No (manual)                   | No (manual)                     | No                                              | No (django-pg-zero-downtime-migrations)       |
| **Failure model**                     | Migrations: batch rollback. Convergence: per-op retry.    | Per-migration, reversible in theory | Per-batch, reversible         | Per-migration, explicit up/down | Forward-only                                    | Per-migration, reversible in theory           |
| **Fresh DB setup**                    | From model definitions (no replay)                        | `schema.rb` dump file               | `schema:dump` SQL file        | `structure.sql` dump            | Replay all migrations                           | Replay all migrations                         |
| **Dependency management**             | Flat timestamps, no graph                                 | Linear timestamps                   | Linear timestamps             | Linear timestamps               | Linear timestamps                               | Per-app dependency graph                      |
| **Reverse migrations**                | No (forward-only, fix-forward)                            | Yes (often broken)                  | Yes (often untested)          | Yes (explicit down)             | No                                              | Yes (often broken)                            |
| **Migration deletability**            | Schema ops deletable, data ops when no longer needed      | Yes (via schema.rb)                 | Yes (via schema:dump)         | Yes (via structure.sql)         | No (history required for shadow DB)             | No (history required for state replay)        |
| **Concurrent migration coordination** | Advisory locks (session-level)                            | Advisory locks (since 5.2)          | Cache-based locks             | Advisory locks (since 3.9)      | None                                            | Table lock (transaction-bound)                |

Notable: Rails, Laravel, and Ecto all require developers to manually write every migration, including indexes and constraints. Django and Prisma auto-detect changes but still put indexes/constraints in migration files. Plain is the only system that separates declarative schema (auto-applied) from imperative changes (migration files).

### Arguments against this design

**"Two systems is more complex than one."** Django has one migration system that handles everything. Plain now has migrations + convergence + a comparison engine. More concepts to understand, more code to maintain.

_Counter:_ Django's "one system" is deceptively complex — ModelState, ProjectState, operation classes, the dependency graph, the autodetector, the schema editor's DDL translation layer, squash/merge machinery. That's ~5,000+ lines of the hardest code in the framework. The two-system design is conceptually simpler (imperative vs declarative) even if it has more named components. And developers never think about convergence — they declare indexes on models and `postgres sync` handles it.

**"The nullable window is a regression."** PG 11+ allows `ADD COLUMN ... NOT NULL DEFAULT 'x'` as a catalog-only operation — instant, no NULLs ever appear. The slim model forces nullable → backfill → NOT NULL across two steps or two deploys. For projects that don't need zero-downtime deploys, this is unnecessary ceremony.

_Counter:_ Convergence applies defaults in pass 0 — immediately after migrations, before anything else. For `postgres sync` on a single server, the nullable window is effectively zero (migration adds column → pass 0 applies SET DEFAULT → new rows get the default). The multi-deploy case only matters for rolling deploys, where the expand-and-contract pattern is what you want anyway. And the PG 11+ optimization only works with non-volatile defaults — `now()`, `gen_random_uuid()`, or any function call still requires a table rewrite. Convergence handles all cases uniformly.

**"Auto-applying schema changes during deploy is scary."** Convergence creates indexes and constraints automatically. What if it starts building a huge index during peak traffic? What if a constraint validation scans a 100M-row table?

_Counter:_ Convergence uses CONCURRENTLY (doesn't block writes), lock_timeout (fails fast if it can't acquire a lock), and the backfill threshold (reports instead of acting on large tables). These are online-safety patterns — they keep DDL from taking the site down. Rollout safety is still handled by deploy sequencing and truthful model declarations. The scary alternative is developers forgetting to use CONCURRENTLY and taking the site down with a regular CREATE INDEX.

**"DB introspection for `migrations create` is fragile."** Alembic does this and has documented caveats. If the dev DB drifts, you generate wrong migrations. Every other auto-detecting tool (Prisma, Atlas) uses a clean ephemeral DB instead.

_Counter:_ The drift check (refuse to generate if DB doesn't match migration state) is the key safeguard that Alembic lacks. And convergence actively keeps the DB in shape — drift is less likely because `postgres sync` is always converging toward the correct state. The ephemeral DB approach (Option C) remains available as an escape hatch if needed.

**"No reverse migrations means harder incident recovery."** "Fix forward" is easy to say, hard to do at 2am when the site is down and the new code has a bug.

_Counter:_ Reverse migrations were already unreliable — 22% of Django projects have irreversible migrations, and most reverse migrations are untested. The real incident recovery is rolling back the code deploy (old code + forward-compatible schema is the expand-and-contract guarantee). If a constraint needs to be dropped in an emergency, `RunSQL` in a new migration or direct psql access is explicit and auditable. Pretending the framework can safely automate reversal gives false confidence.

**"This is a lot of work for a small team."** Comparison engine expansion, convergence engine, new runner, advisory locks, backfill system, CLI redesign, transition tooling — this is months of effort.

_Counter:_ Fair. The sequence is designed so each piece delivers value independently (lock_timeout is one line, advisory locks are a few hundred). But the full vision is ambitious. The question is whether the current system's pain points (unsafe DDL by default, no-op migrations, dependency graph complexity, squash/merge machinery) are bad enough to justify it. For a Postgres-first framework, getting the database story right is foundational — it's worth the investment.

---

## Vision

- **Migrations are simple.** They contain AddField, RemoveField, CreateModel, DeleteModel, and RunPython. No indexes, no constraints, no NOT NULL. Flat timestamped list, no per-app directories, no dependency graph.
- **Schema convergence handles the rest.** Indexes, FK constraints, CHECK constraints, unique constraints, and NOT NULL are declared on models and applied by the framework using online-safe Postgres patterns (CONCURRENTLY, NOT VALID + VALIDATE, CHECK-then-SET-NOT-NULL). Self-healing — run it repeatedly and it converges.
- **One command to sync.** Something like `postgres sync` that runs pending migrations, applies required correctness convergence, and reports best-effort performance work separately.
- **Fresh databases don't need schema history.** `postgres sync` on an empty database creates everything from model definitions, then converges the declared schema. Historical data migrations are incremental concerns, not part of fresh setup. App seeding/init is a separate concern.
- **Safe by default.** `lock_timeout` on all DDL. Advisory locks for migration coordination. Non-blocking DDL for convergence operations. No expert knowledge required.

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

### Remaining: Convergence expansion

More things to move from migrations to convergence. Each of these removes operations from the autodetector and lets the existing migration format get thinner organically.

- [ ] Move FK constraints from field-level migration operations to convergence
- [ ] NOT NULL convergence (backfill + CHECK NOT VALID + VALIDATE + SET NOT NULL)
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

### Two systems, not two directories

Earlier exploration considered Ecto's automatic/manual migration directories. The convergence approach is more elegant — the framework knows that `AddIndex` is inherently different from `AddField` and handles each appropriately. No developer classification needed.

### Why convergence works for indexes/constraints but not columns

The split comes down to **what the code depends on.** A missing column means a hard crash. A missing secondary index means slower queries. Constraints and defaults sit between those extremes: they are declarative like indexes, but correctness-critical like schema shape.

- **Convergence** (indexes, constraints, NOT NULL): per-operation and non-transactional, but with two result classes. Correctness convergence must succeed; performance convergence can degrade and retry.
- **Migrations** (tables, columns, renames, type changes): batch transaction, all-or-nothing. Either all structural changes apply or none do.

We considered making AddColumn and CreateTable convergence-managed too (they're unambiguous — model declares a column, DB doesn't have it, add it). But this creates ordering and transaction problems. A data migration that backfills a new column must run AFTER the column exists. With migrations, this is natural — both are in the batch transaction, timestamp-ordered. With convergence, you'd need structural convergence → data migrations → schema convergence — three phases instead of two, plus logic to distinguish rename migrations (which must run before structural convergence) from data migrations (which run after). The current two-phase design (migrations → convergence) is simpler and safer.

The DX concern (too many commands for the common case) is addressed by `postgres sync` running `migrations create` automatically in DEBUG mode. You get one-command convenience without the ordering complexity.

### Flat timestamps, no dependency graph

The dependency graph exists primarily to coordinate cross-app constraint creation ordering. With constraints in convergence (which runs after all migrations), cross-app dependencies are eliminated. FK fields become just a bigint column in the migration — no reference to the target table needed. Circular FK dependencies, a classic Django pain point, simply don't exist.

### Failure handling: the split gives you both

Today's migration system forces a choice: `atomic=True` (safe rollback but can't use CONCURRENTLY/VALIDATE) or `atomic=False` (enables safe DDL but partial failure leaves you stuck). The split eliminates this tradeoff:

- **Migrations**: batch transaction, all-or-nothing. If any fails, roll back everything. This works because slim migrations are all catalog-only DDL — fast, no long locks. Same safety as today without the downsides.
- **Convergence**: split by semantics, not just mechanism. Correctness convergence (UNIQUE, FK, CHECK, NOT NULL, defaults) is part of "the DB matches the code" and should make `postgres sync` fail if it can't reach the declared state. Performance convergence (secondary indexes) is best-effort — warn, retry later, don't block deploys. "Online-safe" does not automatically mean "rollout-safe"; stricter contracts still need to be declared in the right deploy.

### Rollback story: explicit, not magical

Reverse migrations have a chicken-and-egg problem: the reverse migration lives in the code you just rolled back. To run it, you either need the new code (which you're trying to undo) or git surgery to cherry-pick the migration file into the old code. Every path requires manual intervention during an incident.

The improvement here is not "automatic reverse schema changes." The improvement is a clearer contract:

- Normal `postgres sync` adds and validates declared state. It does **not** auto-drop undeclared indexes/constraints as part of a rollback.
- Cleanup is explicit via `--prune` (or manual SQL / `RunSQL`) because dropping objects in production is a deliberate operation, even when the model no longer declares them.
- Restrictive convergence changes should only be declared in the contract deploy, after old code is gone. If rolling back the code would require dropping a newly-added constraint, that constraint was tightened too early.

This keeps rollback boring: roll back the code, leave additive schema in place, and use explicit cleanup only when you actually want to contract the schema.

For the current scope, that means two deploy shapes:

- Ordinary deploy: `plain postgres sync`
- Contraction deploy: `plain postgres sync --prune`

`--prune` is not meant to be a routine post-deploy cleanup step. It is the explicit marker that this deploy removes convergence-owned schema objects. A more automatic, deploy-aware approach is possible later, but it is a separate design problem. See deploy-aware-rollouts.md.

`postgres schema` completes the picture — after a rollback, it shows exactly what differs between your models and the database, so you can verify the state before and after `postgres sync`.

The two-system split gives you the right rollback behavior for each category: additive changes can remain in place, cleanup is explicit, and destructive structural changes stay fix-forward.

### One comparison engine, three tools

`postgres schema` diffs models against the actual DB (columns, indexes, unique constraints, check constraints, FK constraints). Remaining expansion: `db_default` values. That same engine drives everything:

- `postgres schema` — read-only diff ("here's what's different")
- `migrations create` — generates SQL for the imperative parts (columns, tables)
- `postgres converge` — applies the declarative parts (indexes, constraints, NOT NULL)
- `postgres sync` — runs all three in sequence

This means `migrations create` requires a database connection and a DB in known-good state. Reasonable — you're doing database work, and `postgres schema` / convergence keep the DB in shape. The payoff: no operation abstraction layer, no state replay, no ModelState/ProjectState. The entire state reconstruction machinery is eliminated.

All migrations are `.py` files. Schema migrations use thin operation classes (auto-generated). Data migrations use `run()` (developer-written). The operation set enforces the migration/convergence boundary — there is no `CreateIndex` or `SetNotNull` operation. See slim-migrations.md for details.

### No no-op migrations

Only DB-relevant changes produce migrations. Changing `choices`, `validators`, `default` (non-db), `on_delete`, `related_name`, `ordering`, etc. does NOT generate a migration. The model code is the truth for Python-level properties.

### What migrations contain vs what convergence handles

**Migrations** (imperative, timestamped, tracked):

- CreateModel, DeleteModel
- AddField, RemoveField
- RenameField, RenameModel
- RunPython, RunSQL (data operations)

**Convergence** (declarative, from model state):

- Indexes (CREATE INDEX CONCURRENTLY)
- FK constraints (NOT VALID + VALIDATE) — currently created inline by AddField, moves to convergence
- CHECK constraints (NOT VALID + VALIDATE) — already moved to convergence, autodetector no longer generates AddConstraint/RemoveConstraint
- Unique constraints (concurrent index + USING INDEX)
- NOT NULL (CHECK NOT VALID + VALIDATE + SET NOT NULL, only when no NULLs exist)
- `db_default` (SET DEFAULT / DROP DEFAULT) — new feature, Plain currently uses Python-side defaults only
- Removing any of the above when no longer declared on model

### Package migrations

Packages ship migrations for CreateModel/AddField plus explicit data operations. Indexes and constraints are declared on models and handled by convergence when the package is installed.

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

## What this replaces/subsumes

- `migrations-safety-analysis` future → convergence uses safe patterns by default; remaining safety warnings move into `migrations create` output
- `models-non-blocking-ddl` future → the convergence engine implements all non-blocking DDL patterns
- `enforce-0001-initial-naming` future → no sequential numbering at all
- `migrations-rename-app-column` future → no app column in tracking table
- `migrations squash` command → removed, no longer needed
- `migrations reset` skill → trivial (delete files, `migrations create`, prune)
- `fk-auto-index-removal` arc lessons → convergence manages all indexes from model declarations
