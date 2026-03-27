# Migration rethink

Replace Django's migration system with two complementary systems: **migrations** for imperative schema changes that code depends on, and **schema convergence** for declarative state (indexes, constraints, NOT NULL) that the framework applies automatically using safe Postgres patterns.

The current system bundles everything into migration files — schema changes, index creation, constraint management, dependency graphs — and wraps it all in transactions that hold dangerous locks. The rethink separates what _must_ be imperative (adding/removing columns, data operations) from what can be _declarative_ (the database should match the model definitions), and handles each appropriately.

## How it works (draft docs)

Plain manages your database with two systems: **migrations** for structural changes (tables and columns) and **schema convergence** for everything else (indexes, constraints, NOT NULL). One command runs both.

### The dev loop

```bash
# Edit your model, then:
plain postgres schema --make --sync   # generate migration + apply everything
```

Or step by step:

```bash
plain postgres schema            # see what changed
plain postgres schema --make     # generate a migration
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
$ plain postgres schema --make
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

Migrations run in a single transaction — all pending migrations succeed together or all roll back. No partial state.

For data operations, create a `.py` migration with `--empty`. You can use the ORM — models are imported directly, no historical reconstruction:

```python
# app/migrations/20240320_090000_backfill_status.py
class Migration:
    def run(self, connection):
        from app.models import Order
        Order.query.filter(status=None).update(status="active")
```

### Schema convergence

Indexes, constraints, and NOT NULL are declared on your models. The framework applies them automatically using safe Postgres DDL patterns — you never write migrations for these.

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

Behind the scenes, convergence uses `CREATE INDEX CONCURRENTLY`, `ADD CONSTRAINT ... NOT VALID` + `VALIDATE`, and the CHECK-then-SET-NOT-NULL pattern. If an operation fails (lock timeout, transient error), it retries on the next `postgres sync`.

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

One command. Applies pending migrations, then converges schema. Idempotent — safe to run any number of times.

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

Run `plain postgres schema --make` to create a migration.
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

_Counter:_ Convergence uses CONCURRENTLY (doesn't block writes), lock_timeout (fails fast if it can't acquire a lock), and the backfill threshold (reports instead of acting on large tables). These are the same patterns that production teams apply manually today — convergence just automates them. The scary alternative is developers forgetting to use CONCURRENTLY and taking the site down with a regular CREATE INDEX.

**"DB introspection for makemigrations is fragile."** Alembic does this and has documented caveats. If the dev DB drifts, you generate wrong migrations. Every other auto-detecting tool (Prisma, Atlas) uses a clean ephemeral DB instead.

_Counter:_ The drift check (refuse to generate if DB doesn't match migration state) is the key safeguard that Alembic lacks. And convergence actively keeps the DB in shape — drift is less likely because `postgres sync` is always converging toward the correct state. The ephemeral DB approach (Option C) remains available as an escape hatch if needed.

**"No reverse migrations means harder incident recovery."** "Fix forward" is easy to say, hard to do at 2am when the site is down and the new code has a bug.

_Counter:_ Reverse migrations were already unreliable — 22% of Django projects have irreversible migrations, and most reverse migrations are untested. The real incident recovery is rolling back the code deploy (old code + forward-compatible schema is the expand-and-contract guarantee). If a constraint needs to be dropped in an emergency, `RunSQL` in a new migration or direct psql access is explicit and auditable. Pretending the framework can safely automate reversal gives false confidence.

**"This is a lot of work for a small team."** Comparison engine expansion, convergence engine, new runner, advisory locks, backfill system, CLI redesign, transition tooling — this is months of effort.

_Counter:_ Fair. The sequence is designed so each piece delivers value independently (lock_timeout is one line, advisory locks are a few hundred). But the full vision is ambitious. The question is whether the current system's pain points (unsafe DDL by default, no-op migrations, dependency graph complexity, squash/merge machinery) are bad enough to justify it. For a Postgres-first framework, getting the database story right is foundational — it's worth the investment.

---

## Vision

- **Migrations are simple.** They contain AddField, RemoveField, CreateModel, DeleteModel, and RunPython. No indexes, no constraints, no NOT NULL. Flat timestamped list, no per-app directories, no dependency graph.
- **Schema convergence handles the rest.** Indexes, FK constraints, CHECK constraints, unique constraints, and NOT NULL are declared on models and applied by the framework using safe Postgres patterns (CONCURRENTLY, NOT VALID + VALIDATE, CHECK-then-SET-NOT-NULL). Self-healing — run it repeatedly and it converges.
- **One command to sync.** Something like `postgres sync` that runs pending migrations then converges schema, with clear output about what it did and what's still pending (e.g., NOT NULL blocked by existing NULLs).
- **Fresh databases don't need migration history.** `postgres sync` on an empty database creates everything from model definitions. Migrations only matter for incremental changes to existing databases.
- **Safe by default.** `lock_timeout` on all DDL. Advisory locks for migration coordination. Non-blocking DDL for convergence operations. No expert knowledge required.

## Implementation phases

The rethink ships in four phases. Each phase delivers standalone value. Users don't need to adopt the full vision at once — Phase 1 and 2 improve the existing system without breaking changes. Phase 3 is the major version boundary where migrations change format. Phase 4 is polish.

### Phase 1: Safety (no user-facing changes)

Works with the existing migration system. Each is a standalone PR.

- [ ] [lock-timeout-default](lock-timeout-default.md) — `SET lock_timeout` and `SET statement_timeout` on every DDL statement. One-line change to the schema editor. Biggest safety improvement per line of code.
- [ ] [advisory-locks](advisory-locks.md) — Replace the table lock with session-level advisory lock. Decouples coordination from the transaction. Prerequisite for non-transactional DDL.
- [ ] No-op migration elimination — stop generating migrations for `choices`, `validators`, `default` (non-db), `on_delete`, `related_name`, `ordering`. Autodetector change.

### Phase 2: Convergence (opt-in, coexists with existing migrations)

Ship convergence as a NEW command alongside the existing migration system. Users adopt it gradually.

- [ ] Expand `postgres schema` comparison engine — add FK constraint, CHECK constraint, and default checking
- [ ] [schema-convergence](schema-convergence.md) — the convergence engine (pass 0-5, safe DDL, backfill safety, INVALID index handling)
- [ ] `postgres converge` command — applies what's missing using safe DDL patterns
- [ ] `postgres sync` = existing `migrate` + new `converge`

**Key property:** convergence is purely additive. It reads model declarations and applies what's missing. If an index already exists (created by an old migration), convergence sees it and does nothing. Users can:

- Keep writing index migrations the old way (everything works)
- OR declare indexes on models and let convergence handle them (new way)
- Both approaches coexist in the same project, same database

This is the biggest code effort (convergence engine, comparison engine expansion) but the safest to ship — it's a new command, not a change to existing behavior. Users who never run `postgres converge` see no difference.

### Phase 3: New migration format (breaking change, major version boundary)

`makemigrations` changes format. Convergence becomes the required path for indexes/constraints. Ships as one release with `/plain-upgrade` handling the transition.

- [ ] [thin-operations](thin-operations.md) — new migration format (thin operation classes, boundary enforcement)
- [ ] [slim-migrations](slim-migrations.md) — makemigrations stops generating index/constraint/NOT NULL operations
- [ ] [flat-timestamps](flat-timestamps.md) — single directory, timestamp-based, new tracking table
- [ ] [cli-design](cli-design.md) — `postgres schema --make`, `postgres sync`, hazard gates, `--dry-run` plan
- [ ] [sync-command](sync-command.md) — sync behavior and semantics
- [ ] [failure-handling](failure-handling.md) — batch transaction for migrations, per-operation for convergence, deploy rollback story
- [ ] `postgres adopt-convergence` — one-time validation command for existing projects

**Transition for existing projects:**

1. Upgrade Plain to the Phase 3 release
2. `postgres adopt-convergence` — validates DB matches models, reports any discrepancies
3. Going forward: `postgres schema --make` generates thin operations, convergence handles indexes/constraints
4. Old migration files keep working (runner supports both formats)
5. Delete old files whenever convenient (optional cleanup)

### Phase 4: Benefits that fall out

- [ ] [fresh-db-from-models](fresh-db-from-models.md) — fast test setup, no migration replay
- [ ] [remove-squash](remove-squash.md) — no longer needed
- [ ] DB-free `--check` via operation replay (only after old migration files are cleaned up)
- [ ] `--replay` CI verification (migration history matches models)
- [ ] Migration directory integrity (checksums)

## Key design decisions

### Two systems, not two directories

Earlier exploration considered Ecto's automatic/manual migration directories. The convergence approach is more elegant — the framework knows that `AddIndex` is inherently different from `AddField` and handles each appropriately. No developer classification needed.

### Why convergence works for indexes/constraints but not columns

The split comes down to **what the code depends on.** A missing index means slower queries. A missing column means a hard crash. This drives two different failure models:

- **Convergence** (indexes, constraints, NOT NULL): per-operation, non-transactional, retry on failure. Partial convergence is degraded but functional.
- **Migrations** (tables, columns, renames, type changes): batch transaction, all-or-nothing. Either all structural changes apply or none do.

We considered making AddColumn and CreateTable convergence-managed too (they're unambiguous — model declares a column, DB doesn't have it, add it). But this creates ordering and transaction problems. A data migration that backfills a new column must run AFTER the column exists. With migrations, this is natural — both are in the batch transaction, timestamp-ordered. With convergence, you'd need structural convergence → data migrations → schema convergence — three phases instead of two, plus logic to distinguish rename migrations (which must run before structural convergence) from data migrations (which run after). The current two-phase design (migrations → convergence) is simpler and safer.

The DX concern (too many commands for the common case) is addressed by `postgres schema --make --sync` — auto-generate the migration AND apply in one step. You get one-command convenience without the ordering complexity.

### Flat timestamps, no dependency graph

The dependency graph exists primarily to coordinate cross-app constraint creation ordering. With constraints in convergence (which runs after all migrations), cross-app dependencies are eliminated. FK fields become just a bigint column in the migration — no reference to the target table needed. Circular FK dependencies, a classic Django pain point, simply don't exist.

### Failure handling: the split gives you both

Today's migration system forces a choice: `atomic=True` (safe rollback but can't use CONCURRENTLY/VALIDATE) or `atomic=False` (enables safe DDL but partial failure leaves you stuck). The split eliminates this tradeoff:

- **Migrations**: batch transaction, all-or-nothing. If any fails, roll back everything. This works because slim migrations are all catalog-only DDL — fast, no long locks. Same safety as today without the downsides.
- **Convergence**: per-operation, non-transactional. If one fails, the rest still succeed. Retry failed operations on next run. Failure isn't a deploy blocker — a missing index means slower queries, not broken code.

### One comparison engine, three tools

`postgres schema` already diffs models against the actual DB (columns, indexes, unique constraints). The engine needs expansion to also cover FK constraints, CHECK constraints, and `db_default` values before it can drive convergence fully. That same engine drives everything:

- `postgres schema` — read-only diff ("here's what's different")
- `makemigrations` — generates SQL for the imperative parts (columns, tables)
- `postgres converge` — applies the declarative parts (indexes, constraints, NOT NULL)
- `postgres sync` — runs all three in sequence

This means `makemigrations` requires a database connection and a DB in known-good state. Reasonable — you're doing database work, and `postgres schema` / convergence keep the DB in shape. The payoff: no operation abstraction layer, no state replay, no ModelState/ProjectState. The entire state reconstruction machinery is eliminated.

All migrations are `.py` files. Schema migrations use thin operation classes (auto-generated). Data migrations use `run()` (developer-written). The operation set enforces the migration/convergence boundary — there is no `CreateIndex` or `SetNotNull` operation. See slim-migrations.md for details.

### No no-op migrations

Only DB-relevant changes produce migrations. Changing `choices`, `validators`, `default` (non-db), `on_delete`, `related_name`, `ordering`, etc. does NOT generate a migration. The model code is the truth for Python-level properties. RunPython uses current model code via regular imports, not historical reconstruction.

### What migrations contain vs what convergence handles

**Migrations** (imperative, timestamped, tracked):

- CreateModel, DeleteModel
- AddField, RemoveField
- RenameField, RenameModel
- RunPython, RunSQL (data operations)

**Convergence** (declarative, from model state):

- Indexes (CREATE INDEX CONCURRENTLY)
- FK constraints (NOT VALID + VALIDATE) — currently created inline by AddField, moves to convergence
- CHECK constraints (NOT VALID + VALIDATE) — includes auto-generated field-level checks (e.g., PositiveIntegerField)
- Unique constraints (concurrent index + USING INDEX)
- NOT NULL (CHECK NOT VALID + VALIDATE + SET NOT NULL, only when no NULLs exist)
- `db_default` (SET DEFAULT / DROP DEFAULT) — new feature, Plain currently uses Python-side defaults only
- Removing any of the above when no longer declared on model

### Package migrations

Packages ship migrations for CreateModel/AddField/RunPython. Indexes and constraints are declared on models and handled by convergence when the package is installed. Package data operations (backfills) are RunPython migrations that get discovered and run in timestamp order alongside the project's own migrations.

## Industry context

- **Rails**: `schema.rb` as authoritative snapshot, migrations deletable, `db:schema:load` for fresh DBs. No convergence — but the schema file serves a similar "truth is in the model, not the history" role. The safety ecosystem (strong_migrations, safe-pg-migrations, pg_ha_migrations) provides the safe DDL patterns that convergence bakes in by default.
- **Laravel**: `schema:dump` captures schema + migration records as SQL. Fresh DBs load dump then run post-dump migrations. `--prune` deletes old files.
- **Ecto**: `structure.sql` dump, automatic/manual migration directories for deploy ordering, advisory locks (v3.9+). Jose Valim rejected built-in squash in favor of dump+load.
- **Prisma**: Declarative schema file, auto-generated migration diffs, no data migration support. `db push` for prototyping (applies schema directly without migrations). No safe DDL patterns and no auto-backfill — adding a required column to a populated table simply fails.
- **Atlas** (Go): Declarative schema-as-code with diff-based migration planning. Closest to convergence in philosophy — diffs desired state against actual DB. Uses plan structure (not a dependency graph) to order operations, with concurrent index creation before constraint attachment. 50+ safety analyzers. Does not auto-backfill.
- **pgroll** (Xata): Expand/contract pattern for zero-downtime Postgres migrations. Batched backfills (1,000 rows default, configurable) with inter-batch delay. Manages dual-schema access during migration lifecycle — more complex than convergence needs.

None of these combine declarative convergence with imperative migrations the way this design does. Atlas is the closest parallel for the declarative side but doesn't separate convergence from migrations — everything goes through its plan engine. The Rails safety gems prove the individual patterns work at scale but require manual orchestration that convergence automates.

## What this replaces/subsumes

- `migrations-safety-analysis` future → convergence uses safe patterns by default; remaining safety warnings move into `makemigrations` output
- `models-non-blocking-ddl` future → the convergence engine implements all non-blocking DDL patterns
- `enforce-0001-initial-naming` future → no sequential numbering at all
- `migrations-rename-app-column` future → no app column in tracking table
- `migrations squash` command → removed, no longer needed
- `migrations reset` skill → trivial (delete files, makemigrations, prune)
- `fk-auto-index-removal` arc lessons → convergence manages all indexes from model declarations
