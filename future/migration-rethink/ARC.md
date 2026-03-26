# Migration rethink

Replace Django's migration system with two complementary systems: **migrations** for imperative schema changes that code depends on, and **schema convergence** for declarative state (indexes, constraints, NOT NULL) that the framework applies automatically using safe Postgres patterns.

The current system bundles everything into migration files — schema changes, index creation, constraint management, dependency graphs — and wraps it all in transactions that hold dangerous locks. The rethink separates what _must_ be imperative (adding/removing columns, data operations) from what can be _declarative_ (the database should match the model definitions), and handles each appropriately.

## How it works (draft docs)

Plain manages your database with two systems: **migrations** for structural changes (tables and columns) and **schema convergence** for everything else (indexes, constraints, NOT NULL). One command runs both.

### The dev loop

```bash
# Edit your model, then:
plain postgres schema            # see what changed
plain postgres schema --make     # generate a migration
plain postgres sync              # apply everything
```

### Migrations

Migrations handle adding tables, columns, and renaming things. They're `.sql` files, auto-generated from the diff between your models and the database.

```python
@postgres.register_model
class Order(postgres.Model):
    title: str = types.CharField(max_length=255)
    status: str = types.CharField(max_length=50)
```

```
$ plain postgres schema --make
Created: app/migrations/20240315_110000_add_status_to_orders.sql
```

```sql
-- app/migrations/20240315_110000_add_status_to_orders.sql
ALTER TABLE orders ADD COLUMN status varchar(50) NULL;
```

Migrations run in a single transaction — all pending migrations succeed together or all roll back. No partial state.

For data operations, create a `.py` migration with `--empty`. You can use the ORM — models are imported directly, no historical reconstruction:

```python
# app/migrations/20240320_090000_backfill_status.py
class Migration:
    def run(self, connection):
        from app.models import Order
        Order.query.filter(status=None).update(status="active")
```

Raw SQL is also available via `connection` when the ORM doesn't fit:

```python
class Migration:
    def run(self, connection):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE orders SET status = 'active' WHERE status IS NULL")
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

---

## Vision

- **Migrations are simple.** They contain AddField, RemoveField, CreateModel, DeleteModel, and RunPython. No indexes, no constraints, no NOT NULL. Flat timestamped list, no per-app directories, no dependency graph.
- **Schema convergence handles the rest.** Indexes, FK constraints, CHECK constraints, unique constraints, and NOT NULL are declared on models and applied by the framework using safe Postgres patterns (CONCURRENTLY, NOT VALID + VALIDATE, CHECK-then-SET-NOT-NULL). Self-healing — run it repeatedly and it converges.
- **One command to sync.** Something like `postgres sync` that runs pending migrations then converges schema, with clear output about what it did and what's still pending (e.g., NOT NULL blocked by existing NULLs).
- **Fresh databases don't need migration history.** `postgres sync` on an empty database creates everything from model definitions. Migrations only matter for incremental changes to existing databases.
- **Safe by default.** `lock_timeout` on all DDL. Advisory locks for migration coordination. Non-blocking DDL for convergence operations. No expert knowledge required.

## Sequence

- [ ] [lock-timeout-default](lock-timeout-default.md)
- [ ] [advisory-locks](advisory-locks.md)
- [ ] [schema-convergence](schema-convergence.md)
- [ ] [failure-handling](failure-handling.md)
- [ ] [thin-operations](thin-operations.md)
- [ ] [slim-migrations](slim-migrations.md)
- [ ] [flat-timestamps](flat-timestamps.md)
- [ ] [cli-design](cli-design.md)
- [ ] [sync-command](sync-command.md)
- [ ] [fresh-db-from-models](fresh-db-from-models.md)
- [ ] [remove-squash](remove-squash.md)

## Key design decisions

### Two systems, not two directories

Earlier exploration considered Ecto's automatic/manual migration directories. The convergence approach is more elegant — the framework knows that `AddIndex` is inherently different from `AddField` and handles each appropriately. No developer classification needed.

### Why convergence works for indexes/constraints

These operations share key properties: they're declarative (desired state is on the model), idempotent (can retry safely), independent (no ordering between them), and code doesn't depend on them existing (the app works without an index, just slower). Migrations are the opposite: imperative, ordered, one-time, and code depends on them.

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

Schema migrations are `.sql` files (pure SQL, auto-generated). Data migrations are `.py` files (developer-written Python). Both sorted by timestamp. Fresh databases skip `.sql` files (schema from models) and run `.py` files (data operations). See slim-migrations.md for details.

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
