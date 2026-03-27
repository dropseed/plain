# Schema convergence

## Problem

Indexes, constraints, and NOT NULL are currently managed through migration files. This means:

- Developers must know about CONCURRENTLY, NOT VALID, and the CHECK-then-NOT-NULL pattern
- The migration system wraps everything in transactions that prevent safe DDL patterns
- Migration files accumulate index/constraint operations that bloat the history
- Cross-app FK dependencies exist solely because the migration creating a FK constraint needs the target table
- Adding an index requires generating a migration file for what is purely a declarative statement

## Solution

A convergence engine that compares model declarations against the actual database schema and applies the difference using safe Postgres patterns. Builds on the existing `postgres schema` command which already does the comparison — this adds the ability to act on it.

The `postgres schema` comparison engine becomes the foundation for the entire rethink. The same model-vs-DB diff drives `postgres schema` (read-only view), `makemigrations` (generate SQL for column/table changes), and `postgres converge` (apply indexes/constraints/NOT NULL). One engine, three modes.

### What convergence manages

| Declaration                           | Safe pattern used                                                                                      |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `Index(fields=["email"], name="idx")` | `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY`                                                |
| `ForeignKeyField(User)` constraint    | `ADD CONSTRAINT FK NOT VALID` then `VALIDATE CONSTRAINT`                                               |
| `CheckConstraint(...)`                | `ADD CONSTRAINT CHECK NOT VALID` then `VALIDATE CONSTRAINT`                                            |
| `UniqueConstraint(...)`               | `CREATE UNIQUE INDEX CONCURRENTLY` then `ADD CONSTRAINT USING INDEX`                                   |
| NOT NULL (field without `null=True`)  | Backfill NULLs with model default (if available) → `ADD CHECK NOT VALID` → `VALIDATE` → `SET NOT NULL` |
| Removal of any of the above           | Safe drop pattern                                                                                      |

### Behavior

- **Idempotent**: run repeatedly, it converges. Failed operations are retried on next run.
- **Self-healing**: detects INVALID indexes from failed CONCURRENTLY builds, drops and retries them.
- **Auto-backfills with safety limits**: if a NOT NULL column has NULLs and the model declares a default, convergence can backfill before applying the constraint — but only when safe. See "Backfill safety" section below for thresholds and behavior. Reports a blocker when there's no default and NULLs exist (requires a RunPython migration with custom logic), or when the table exceeds the auto-backfill threshold.
- **Non-destructive by default**: adding things is automatic, but dropping an index/constraint that exists in DB but not in model could prompt for confirmation (or have a `--prune` flag).

### Dev vs production behavior

In development (no concurrent traffic), convergence could skip CONCURRENTLY and use simpler patterns for speed. In production, always use the safe patterns. Detection could be based on a setting or `--dev` flag.

### Current state of `postgres schema`

`postgres schema` already exists and compares models against the DB. Today it checks columns (existence, type, nullability), indexes (by name), and unique constraints (by name). It does **not** yet check FK constraints or CHECK constraints. Convergence requires expanding the comparison engine to cover all managed object types.

### How `postgres schema` evolves

`postgres schema` becomes the read-only view of what convergence would do:

```
$ plain postgres schema
✓ users — 3 columns, 2 indexes, 1 constraint — all match
✗ orders — missing index orders_user_id_idx
✗ orders — status: nullable in DB, NOT NULL in model (12 NULL rows)
```

Convergence is the write mode:

```
$ plain postgres converge
✓ Created index orders_user_id_idx (CONCURRENTLY)
⏸ orders.status: NOT NULL blocked — 12 rows have NULLs
  Run: plain postgres backfill orders.status
```

## Ownership: what convergence manages vs ignores

Convergence only manages objects that match a declaration on a model. The **name** is the ownership key.

- `Index(fields=["email"], name="users_email_idx")` → convergence owns `users_email_idx`
- `UniqueConstraint(fields=["email"], name="users_email_unique")` → convergence owns `users_email_unique`
- `ForeignKeyField(User)` with `db_constraint=True` → convergence owns the FK constraint (name derived from field)
- An index someone created via psql or RunSQL with a different name → convergence ignores it
- An old auto-generated index from Django/Plain's FK auto-indexing → convergence ignores it (it has no matching model declaration)

All indexes and constraints require explicit names (`Index.name` and `UniqueConstraint.name` are required, not auto-generated). There is no `db_index=True` field shorthand and no `unique=True` field option — all indexes use `model_options.indexes`, all unique constraints use `model_options.constraints`. FK constraints are the exception: they're implied by `ForeignKeyField(db_constraint=True)` (the default).

**Auto-generated field-level CHECK constraints** (e.g., `PositiveIntegerField` generates `CHECK (value >= 0)`) are currently created inline during AddField. These move to convergence — the field type implies the constraint, convergence applies it using the NOT VALID + VALIDATE pattern. The constraint name is derived from the field, not user-declared.

This means: convergence never touches things it didn't create (or that aren't declared). No surprises from manual DB work, extensions, or legacy objects. The tradeoff is that duplicate indexes can exist (one convergence-managed, one legacy) — `postgres schema` should report these as informational.

## Convergence ordering

The ARC doc describes convergence operations as "independent" — but they're not fully independent at the Postgres level. Several operations have hard ordering requirements, and others benefit from sequencing for performance. Convergence uses a fixed multi-pass execution order to handle this.

### Why ordering matters

Three concrete dependency chains exist:

1. **Unique constraints require their index first.** `ADD CONSTRAINT ... USING INDEX` requires the index to already exist, be a valid b-tree with default sort ordering, and not be a partial or expression index. The index must be built with `CREATE UNIQUE INDEX CONCURRENTLY` before the constraint can reference it. This is a hard Postgres requirement — the `USING INDEX` clause fails if the index doesn't exist.

2. **NOT NULL requires backfill and validation first.** The safe pattern is: backfill NULLs → `ADD CHECK (col IS NOT NULL) NOT VALID` → `VALIDATE CONSTRAINT` → `SET NOT NULL`. The `SET NOT NULL` at the end skips its own table scan because Postgres recognizes that a valid CHECK constraint already proves no NULLs exist (documented behavior: "if a valid CHECK constraint is found which proves no NULL can exist, then the table scan is skipped"). Without the validated CHECK, `SET NOT NULL` does a full table scan under ACCESS EXCLUSIVE — exactly what we're trying to avoid.

3. **FK validation benefits from the FK index.** `VALIDATE CONSTRAINT` on a foreign key scans the child table and looks up each referenced value in the parent. If there's an index on the FK column in the child table, this scan is faster. Not a hard requirement, but creating the FK index before validating the FK constraint avoids a potentially slow sequential scan during validation.

### Execution passes

Convergence runs in five ordered passes. Each pass completes fully before the next begins. Within a pass, operations are independent and could be parallelized in the future.

```
Pass 0: Defaults (SET DEFAULT, DROP DEFAULT)
  - Applies defaults from model declarations — both static values and DB expressions
    (e.g., SET DEFAULT 'pending', SET DEFAULT gen_random_uuid(), SET DEFAULT now())
  - Runs FIRST to close the nullable window: after a migration adds a nullable column,
    SET DEFAULT ensures new rows immediately get the correct value
  - Catalog-only, instant — even for DB expression defaults like gen_random_uuid()
  - See fields-db-defaults.md for the full design of DB expression defaults

Pass 1: Indexes (CREATE INDEX CONCURRENTLY, DROP INDEX CONCURRENTLY)
  - Creates all missing indexes, including unique indexes needed by unique constraints
  - Detects and replaces INVALID indexes (drop + recreate)
  - Detects index definition changes (same name, different columns/type/condition)
    and reports them — see "Index modification detection" below

Pass 2: Constraints — initial (ADD CONSTRAINT ... NOT VALID, ADD CONSTRAINT ... USING INDEX)
  - FK constraints: ADD CONSTRAINT ... NOT VALID (SHARE ROW EXCLUSIVE lock, no scan)
  - CHECK constraints: ADD CONSTRAINT ... NOT VALID (ACCESS EXCLUSIVE lock, instant)
  - Unique constraints: ADD CONSTRAINT ... USING INDEX (instant, uses index from pass 1)
  - NOT NULL: ADD CHECK (col IS NOT NULL) NOT VALID (ACCESS EXCLUSIVE lock, instant)

Pass 3: Validation (VALIDATE CONSTRAINT)
  - Validates all NOT VALID constraints from pass 2 (SHARE UPDATE EXCLUSIVE lock — reads/writes continue)
  - Also validates any pre-existing NOT VALID constraints from prior failed runs

Pass 4: NOT NULL finalization (SET NOT NULL)
  - For columns with a validated CHECK (col IS NOT NULL): SET NOT NULL (skips table scan)
  - Drops the temporary CHECK constraint after SET NOT NULL succeeds
  - Skipped if validation failed (constraint stays NOT VALID, retried next run)

Pass 5: Cleanup (constraint/index drops)
  - Drops constraints/indexes no longer declared on models (with --prune or confirmation)
```

### Why five passes, not a dependency graph

The Django autodetector uses a topological sort with per-operation dependency edges (via `TopologicalSorter` from `graphlib`). This is necessary when operations are heterogeneous (CreateModel, AddField, AddIndex all interleaved across apps). Convergence is simpler — it only manages a known set of operation types, all following the same dependency pattern. A fixed pass order is:

- **Predictable**: operators know what happens in what order. No graph to debug.
- **Correct by construction**: pass 1 always runs before pass 2, so indexes always exist before `USING INDEX`. No edge cases from graph cycles or missing dependencies.
- **Debuggable**: if pass 3 fails, you know passes 1-2 succeeded. Log output groups by pass.

Atlas takes a similar approach — its declarative diff generates a plan with concurrent indexes created before constraints that reference them, enforced by plan structure rather than a general-purpose dependency solver.

### Lock budget per pass

Each pass has different lock characteristics:

| Pass           | Lock acquired                                                 | Duration                             | Blocks writes? |
| -------------- | ------------------------------------------------------------- | ------------------------------------ | -------------- |
| 0: Defaults    | ACCESS EXCLUSIVE                                              | Milliseconds (catalog-only)          | Briefly        |
| 1: Indexes     | SHARE UPDATE EXCLUSIVE (concurrent)                           | Minutes for large tables             | No             |
| 2: Constraints | SHARE ROW EXCLUSIVE (FK) or ACCESS EXCLUSIVE (CHECK/NOT NULL) | Milliseconds (no scan)               | Briefly        |
| 3: Validation  | SHARE UPDATE EXCLUSIVE                                        | Seconds to minutes (scans data)      | No             |
| 4: NOT NULL    | ACCESS EXCLUSIVE                                              | Milliseconds (scan skipped by CHECK) | Briefly        |
| 5: Cleanup     | Varies                                                        | Milliseconds                         | Briefly        |

The expensive passes (1, 3) don't block writes. The blocking passes (0, 2, 4, 5) complete in milliseconds because they skip scans. Pass 0 runs first to close the nullable window immediately after migrations add new columns.

### Index modification detection

When a model's index declaration changes (different columns, different type, added WHERE clause) but keeps the same name, convergence sees the existing index doesn't match the declaration. It can't modify an index in place — Postgres requires drop + create.

For small tables this is fine. For large tables, rebuilding an index CONCURRENTLY can take minutes. Convergence handles this by:

1. Detecting the mismatch: "index `orders_status_idx` exists but definition differs from model"
2. Creating a new index with a temporary name CONCURRENTLY (non-blocking)
3. Dropping the old index CONCURRENTLY
4. Renaming the new index to the declared name

This avoids any window where the index doesn't exist. The old index serves queries while the new one builds. The rename is instant (catalog-only).

If the index name itself changes (old name removed from model, new name added), convergence sees an unmanaged index and a missing index — it creates the new one and reports the old one for `--prune`.

## Backfill safety

Auto-backfilling NULLs with model defaults sounds convenient, but silently running `UPDATE orders SET status = 'active' WHERE status IS NULL` on a 10M-row table during deploy is dangerous. Production concerns: long-running UPDATE holding row locks, WAL bloat and replication lag, checkpoint pressure, and connection pool exhaustion if the backfill blocks other operations.

Backfills use the SQL expression from the model's default. Static defaults produce uniform values (`SET status = 'pending'`). DB expression defaults (see fields-db-defaults.md) produce per-row values (`SET uuid = gen_random_uuid()` — each row gets a unique UUID). This is strictly better than the current migration system where callable defaults are evaluated once in Python, giving every row the same value.

Note: `ALTER TABLE ADD COLUMN ... DEFAULT gen_random_uuid() NOT NULL` as a single DDL statement would also give per-row values, but triggers a table rewrite for volatile defaults — ACCESS EXCLUSIVE for the duration. The convergence approach (add nullable column → SET DEFAULT → batch backfill → NOT NULL) avoids the rewrite by backfilling in batches outside a transaction. Safer for large tables.

### What production tools do

- **pgroll**: Batches of 1,000 rows (configurable via `--backfill-batch-size`), with configurable delay between batches (`--backfill-batch-delay`). No automatic threshold — the operator decides.
- **safe-pg-migrations**: Default batch size of 100,000 rows with 0.5s pause between batches. Has an optional `default_value_backfill_threshold` — migrations fail if the table exceeds the configured row count.
- **strong_migrations**: Recommends batches of 10,000 rows with `sleep()` throttling, always outside a transaction. No built-in threshold, but advises "you probably don't need this gem for smaller projects."
- **pg_ha_migrations**: No built-in batching — relies on the developer to write safe backfill logic.
- **Prisma**: No auto-backfill at all. Adding a required column to a table with existing rows fails with an error telling the developer to add it as optional first.

### Decision: threshold-gated auto-backfill

Convergence auto-backfills only when the NULL row count is below a configurable threshold. Above the threshold, it reports the situation and the developer must backfill explicitly.

**Threshold default: 100,000 rows.** This is a pragmatic number — large enough to cover most tables in most projects (admin tables, config tables, lookup tables), small enough that the UPDATE completes in seconds without meaningful WAL or lock impact. safe-pg-migrations uses the same default for its batch size, and it's well within the range where a batched UPDATE is safe.

**Behavior:**

```
# Table has 500 NULL rows, model has default="active"
$ plain postgres converge
✓ orders.status: backfilled 500 NULL rows with 'active' (in 3 batches)
✓ orders.status: NOT NULL applied

# Table has 2M NULL rows
$ plain postgres converge
⏸ orders.status: NOT NULL blocked — 2,000,000 rows have NULLs (exceeds auto-backfill threshold of 100,000)
  Run: plain postgres backfill orders.status --batch-size 10000
```

**Backfill mechanics** (when auto-backfill proceeds):

- Batches of 10,000 rows, each in its own transaction (row locks held briefly)
- 100ms pause between batches to yield to other connections
- No long-running transaction, no full-table lock
- Progress reported: `"backfilling orders.status: 3,000 / 8,500 rows"`

**Configuration:**

```python
# settings.py
POSTGRES_CONVERGE = {
    "BACKFILL_THRESHOLD": 100_000,  # NULL rows; 0 to disable auto-backfill entirely
    "BACKFILL_BATCH_SIZE": 10_000,
    "BACKFILL_BATCH_DELAY": 0.1,  # seconds between batches
}
```

**Manual backfill command** (for tables above threshold or custom logic):

```
$ plain postgres backfill orders.status
  Backfilling orders.status with default 'active'...
  10,000 / 2,000,000 rows (0.5%)
  20,000 / 2,000,000 rows (1.0%)
  ...
  ✓ Backfill complete. Run 'postgres converge' to apply NOT NULL.
```

The `--batch-size` and `--batch-delay` flags override settings for one-off runs. The `--dry-run` flag shows what would be backfilled without executing.

## Failure modes and edge cases

### Concurrent convergence (multi-node deploy)

Two deploy instances run `postgres sync` simultaneously. Migrations are serialized by advisory lock. But convergence could race:

- Both try `CREATE INDEX CONCURRENTLY users_email_idx`
- Second one fails: "relation already exists"
- This is fine if convergence handles the error gracefully (check if index now exists and is valid)

**The INVALID index trap**: if the first one fails mid-build and leaves an INVALID index, the second one's `IF NOT EXISTS` silently succeeds — it sees the name exists and stops, even though the index is INVALID. Both nodes think it's done.

**Solution**: convergence must check `pg_index.indisvalid` after creating, not just `IF NOT EXISTS`. If an index exists but is INVALID, drop it and retry. Convergence also needs its own advisory lock (separate key from the migration lock) to serialize convergence operations.

### Branch switching

Developer is on branch A with `Order.priority` field and index. Switches to branch B which doesn't have that field.

**What happens**: the `priority` column sits in the DB. Convergence on branch B:

- Doesn't see `priority` in any model → ignores the column entirely
- Doesn't see the index on `priority` in any model → ignores it (it's "unmanaged")
- No data loss, no errors

Switch back to branch A:

- `priority` column still exists with its data
- Index still exists
- Convergence confirms everything matches, does nothing

**The migration problem is harder**: if branch A has a migration `AddField priority` that branch B doesn't have, the migration tracking table says it's been applied. Switching to branch B: migration file doesn't exist, but record does. This is the same problem Django has today — convergence doesn't make it worse.

**Related**: the postgres parallel-dev / branch DB workflow (separate databases per git branch) is a complementary approach that sidesteps this entirely. Convergence makes that workflow easier — fresh branch DB setup is just `postgres sync` from models.

### Rolling deploys and NOT NULL

During a rolling deploy, old code doesn't write to a new column. New code does.

1. Migration adds nullable column (applied first, by one node)
2. Old nodes: still running, create rows with NULL in new column
3. New nodes: start writing values to new column
4. Convergence checks NOT NULL: NULLs exist → skips, reports
5. Eventually all nodes on new code, NULLs stop appearing
6. Developer runs backfill for old rows
7. Next convergence: zero NULLs → applies NOT NULL safely

This works naturally. Convergence's "check before acting" approach handles rolling deploys without coordination. The question is visibility — the operator needs to know that NOT NULL is pending and why.

### Column type mismatches

Model says `TextField()`, DB has `varchar(255)`. Is this convergence or migration?

**Answer: migration.** Column type changes are imperative — they may need data transformation, they take ACCESS EXCLUSIVE + potential table rewrite, and the developer needs to consciously choose to do them. Convergence should **detect and report** type mismatches (as `postgres schema` already does) but never attempt to fix them.

### Autodetector blind spot: db_type changes within the same field class

The migration autodetector compares `deconstruct()` output (class path + kwargs) between old migration state and current models. It never calls `db_type()`. This means if a field class changes its SQL type without changing its deconstruct output, **no migration is generated** — existing databases silently diverge from new databases.

This matters in practice when:

- A field class changes its parent (e.g. EmailField moved from CharField to TextField — the db_type changed from `character varying(254)` to `text`, but deconstruct still says `plain.postgres.EmailField`)
- A framework update changes `db_type_sql` on a field class without changing its kwargs

The root cause: migration state loads the **current** class definition to reconstruct old state. There's no record of what SQL type a migration actually produced — it's always derived at runtime.

`postgres schema` solves the **detection** side (comparing models against the actual DB catches these mismatches). But `makemigrations` can't **generate** the AlterField because both old and new resolve identically. The developer must write the ALTER manually or use `postgres schema` output to create a migration.

A potential fix: `makemigrations` could compare the expected schema (from replaying migrations on a fresh DB) against model-derived DDL. If they differ, generate an AlterField. This is essentially `--replay` as a generation step rather than just a verification step.

### `db_default` changes

**Note: `db_default` is a planned feature, not yet implemented.** Plain currently uses Python-side defaults only — when a column is created with a default, the schema editor drops the in-database default immediately after column creation. `db_default` would be a new field parameter that tells Postgres to maintain the default.

Model changes `db_default` from `"active"` to `"pending"`. This is a `SET DEFAULT` — catalog-only, completes in milliseconds regardless of table size. The new default only affects future INSERTs; existing rows are untouched.

**Decision: convergence manages `db_default`.** The reasoning:

1. **It's declarative state.** `db_default` is a property of the column declared on the model. Convergence manages all other declarative column properties (NOT NULL, constraints, indexes) — carving out an exception for defaults would be arbitrary.
2. **It's instant and safe.** `SET DEFAULT` is a catalog-only metadata update (confirmed by Postgres docs: "The new default value will only apply in subsequent INSERT or UPDATE commands; it does not cause rows already in the table to change"). No table scan, no rewrite. The only cost is acquiring an ACCESS EXCLUSIVE lock for a few milliseconds, which `lock_timeout` handles.
3. **No data loss risk.** Changing a default never modifies existing rows. The worst case is new rows get the new default before the developer intended — but the developer changed the model, so they intended it.
4. **Existing rows are a separate concern.** If the developer also needs to update existing rows from "active" to "pending", that's a data migration (RunPython). Convergence should report the change clearly: `"orders.status: db_default changed from 'active' to 'pending' (existing rows unchanged)"`.

The alternative (migration) was considered but rejected. Requiring a migration file for a catalog-only metadata change that the model already declares adds ceremony without safety benefit. No production tool reviewed (Atlas, Prisma, pgroll) treats DEFAULT changes as requiring special safety handling — they're universally treated as instant schema state.

### Custom/extension objects

Tables from extensions (PostGIS geometry_columns, pg_trgm), materialized views, custom functions — convergence ignores all of these. It only operates on tables that correspond to registered models, and only on indexes/constraints that match names declared on those models.

### Partially applied convergence

Convergence creates 3 of 5 indexes, then fails on the 4th (e.g., unique index fails due to duplicate data). The 3 successful indexes are committed (non-transactional). Next run: convergence sees 3 exist, creates the remaining 2 (retrying the failed one). This is the "self-healing" property.

For NOT VALID + VALIDATE patterns: if NOT VALID succeeds but VALIDATE fails (e.g., FK references nonexistent row), the unvalidated constraint exists. New writes are checked, but old data isn't proven valid. Next convergence run retries VALIDATE. The data issue must be fixed before VALIDATE can succeed.

### Unique constraint window during CONCURRENTLY builds

When convergence creates a unique constraint, it builds a unique index CONCURRENTLY (pass 1), then attaches it as a constraint (pass 2). During the index build, there's a window where duplicates can be inserted.

**How Postgres CONCURRENTLY works internally:**

```
Transaction 1: Register index in catalog (indisready=false, indisvalid=false)
                → index exists but is invisible, no writes go to it

Transaction 2: First table scan — builds index entries from existing rows
                → NEW INSERTS DO NOT CHECK UNIQUENESS (indisready=false)
                → this is the vulnerable window
                After scan: set indisready=true, commit

Transaction 3: Second table scan — catches rows modified since first scan
                → uniqueness IS enforced on new inserts (indisready=true)
                → if duplicates were inserted during first scan, BUILD FAILS
                After scan: set indisvalid=true
```

The window is the **first scan duration only** — not the full build. For a 1M-row table, that's seconds. For 100M rows, a minute or so.

**Failure is loud, not silent.** If a duplicate IS inserted during the window:

- The second scan discovers the violation
- `CREATE INDEX CONCURRENTLY` fails, leaving an INVALID index
- The INVALID index still blocks future duplicates (write overhead but enforces uniqueness)
- Convergence detects the INVALID index on next run, drops it, retries
- The duplicate rows exist in the table until discovered and cleaned up

**No tool solves this differently.** pg-schema-diff (Stripe), Atlas, and pgroll all use the same CONCURRENTLY mechanism. There is no Postgres primitive for "start rejecting duplicates immediately but defer the full scan." `NOT VALID` is only supported for CHECK and FK constraints, not UNIQUE. The tradeoff is fundamental: non-concurrent (zero window, blocks all writes) vs concurrent (has window, allows writes).

**Practical risk:** For small/medium tables (< 10M rows), the window is seconds. The probability of a duplicate being inserted during those seconds is low. For large tables with high write rates on uniqueness-critical columns, the risk is real but the consequence is a failed build (loud), not silent corruption.

**Defense in depth:**

1. **Application-level validation** — check for existing records before INSERT (forms, views, API endpoints). This is good practice regardless.
2. **The CONCURRENTLY build's second scan** catches duplicates and fails loudly.
3. **Convergence self-healing** — detects INVALID indexes, drops and retries on next run.
4. **Dev mode** — in development, convergence skips CONCURRENTLY and uses regular `CREATE UNIQUE INDEX` inside a transaction. Zero window. The concurrent window only exists in production where it's an acceptable tradeoff.

### RunPython and fresh databases

**Decision: all RunPython/RunSQL operations replay on fresh databases.** Schema operations (AddField, CreateModel) are skipped since the schema already exists from model-based DDL. No flag, no separate seed mechanism, no classification burden.

Backfill migrations are no-ops on empty tables. Seed migrations insert the data the application needs. See fresh-db-from-models.md for the full rationale and industry comparison.

## Transition from existing projects

Every existing Plain project has migration files full of AddIndex, AddConstraint, AlterField (for NOT NULL changes), etc. These have been applied. The transition must get from "everything tracked in migrations" to "indexes/constraints/NOT NULL managed by convergence" without breaking anything or requiring a database reset.

### How other tools handle this

**Prisma (baselining)**: When adopting Prisma Migrate on an existing database, you generate a baseline migration from your current schema with `prisma migrate diff --from-empty --to-schema`, then mark it as already applied with `prisma migrate resolve --applied`. The baseline represents "everything up to this point already exists." Future migrations build on top. Simple, one-time, no database changes.

**Atlas (baseline + import)**: Atlas provides two paths. `atlas schema inspect` exports the current DB as code, then `atlas migrate diff baseline` generates a migration capturing current state, marked as applied with `--baseline`. Atlas also has `atlas migrate import` that converts migration directories from other systems (Flyway, golang-migrate, Goose) into Atlas format. Both paths end at the same place: a known starting point for future migrations.

**Rails (schema.rb)**: Rails' `schema.rb` has always been the authoritative snapshot. When adding `structure.sql` support, there was no migration needed — you run `db:schema:dump` to generate it, and from then on that file is maintained. The transition is just "start generating the new format." Old migration files are irrelevant.

**Laravel (schema:dump)**: `php artisan schema:dump` captures the current schema as SQL. `--prune` deletes old migration files. Fresh databases load the dump then run post-dump migrations. The transition is a single command.

The pattern across all of these: **snapshot current state, mark it as the starting point, move forward with the new system.** No one attempts to rewrite history or reinterpret old migration files.

### Design for Plain

The transition is a one-time `postgres adopt-convergence` command. It requires a database connection (same as `makemigrations` in the new system — you're doing database work).

**What it does:**

1. **Reads model declarations**: collects all indexes, constraints, NOT NULL, FK constraints, CHECK constraints, and unique constraints declared on models.

2. **Compares against the database**: uses the existing `postgres schema` comparison engine to verify each declared object exists in the DB. This is the same diff that convergence will use going forward.

3. **Reports discrepancies**: if a model declares an index that doesn't exist in the DB (migration was never applied, or was applied to a different DB), it reports this clearly. The developer must resolve it before adopting — either apply the pending migration or update the model.

4. **Reports what convergence now manages**: lists every object that moved from migration-managed to convergence-managed, so the developer sees exactly what changed.

**What it does NOT do:**

- Does not modify the database. The schema is already correct (migrations were applied).
- Does not delete or modify old migration files. They're history.
- Does not require a fresh database or data loss.
- Does not run any convergence operations. It just validates the starting point.

**Example session:**

```
$ plain postgres adopt-convergence

Scanning models...
  users — 2 indexes, 1 FK constraint, 3 NOT NULL columns
  orders — 3 indexes, 2 FK constraints, 1 CHECK constraint, 5 NOT NULL columns
  products — 1 index, 0 constraints, 2 NOT NULL columns

Comparing against database...
  ✓ users — all 6 objects exist in DB
  ✓ orders — all 11 objects exist in DB
  ✓ products — all 3 objects exist in DB

All model-declared objects verified in database.

Going forward:
  - `makemigrations` will skip index/constraint/NOT NULL operations
  - `postgres converge` will manage these objects declaratively
  - `postgres sync` will run migrations then converge
  - Old migration files are untouched — they're history

Run `postgres schema` to verify the current state matches your models.
```

**Error case:**

```
$ plain postgres adopt-convergence

Scanning models...
  ...

Comparing against database...
  ✗ orders — missing index orders_priority_idx
    Model declares Index(fields=["priority"], name="orders_priority_idx")
    but the index does not exist in the database.

Cannot adopt convergence with discrepancies.
Fix: apply pending migrations first, or remove the index declaration from the model.
```

### Why no marker file

A migration or marker file would be the Django instinct — "record the transition as a migration operation." But convergence is stateless by design (it always compares desired vs actual). Convergence doesn't need a marker to know what to do — it diffs models against the DB every time.

The question is whether `makemigrations` needs to know. The answer: **no, because `makemigrations` always generates slim migrations in the new system.** The switch from full to slim migrations is a framework version change, not a per-project configuration. When you upgrade to the version of Plain that includes convergence, `makemigrations` stops generating index/constraint operations. Period.

This means `adopt-convergence` is **a validation command, not a state transition.** It confirms the DB matches models before you start using `postgres converge`. It's strongly recommended but the system works without it — convergence will diff models against the DB regardless.

This is the same approach Atlas takes with its declarative mode. `atlas schema apply` works against any database state. Baselining is recommended for auditability but the engine doesn't require it.

### What about projects that skip adopt-convergence?

If a developer upgrades to the convergence-aware version of Plain without running `adopt-convergence`:

- `makemigrations` generates slim migrations (no index/constraint operations). This is correct — those operations are now convergence's job.
- `postgres converge` compares models to DB. If the DB already has all the right indexes/constraints (from old migrations), convergence says "everything matches" and does nothing. This is also correct.
- The only risk is if the DB is missing objects that old migrations should have created. `postgres schema` will report these, and `postgres converge` will create them.

So the system is self-correcting. `adopt-convergence` catches problems early, but convergence handles them regardless.

### Handling legacy indexes with wrong names

Old auto-generated indexes (from Django/Plain's FK auto-indexing, or default index naming) may have names that don't match the convergence naming convention. Convergence uses the name declared on the model, so:

- Model declares `Index(fields=["user_id"], name="orders_user_id_idx")`
- DB has `orders_user_id_7f3e2a_idx` (Django's auto-generated name)
- Convergence sees `orders_user_id_idx` doesn't exist, creates it
- DB now has two indexes on the same column(s)

`postgres schema` should detect and report duplicate indexes (same columns, different names). The developer can then drop the legacy index manually or via `RunSQL`. Convergence never drops indexes it doesn't own.

`adopt-convergence` should flag these specifically: "Found existing index `orders_user_id_7f3e2a_idx` on the same columns as declared `orders_user_id_idx`. After convergence creates the new index, consider dropping the legacy one."

## Open questions

- Should convergence auto-run after `migrations apply`? Or stay a separate explicit step? **Resolved: combined via `postgres sync` but individually accessible.** `postgres sync` runs migrations then converge. `postgres converge` is available standalone for re-runs, retries, and CI.
- Should convergence track what it's done (its own log/table) or just always compare desired vs actual? **Resolved: stateless.** Always compare desired vs actual. No tracking table, no state to corrupt. This matches how Atlas works — pure diff, no history. pgroll tracks state because it manages the expand/contract lifecycle, but convergence operations are simpler (no dual-schema phase).
- How does this interact with `postgres schema` checks in CI? Should `postgres schema --check` fail if convergence hasn't been run? **Resolved: yes.** `postgres schema --check` should exit non-zero if convergence operations are pending. This catches "forgot to run converge" in CI. It should distinguish between actionable items (missing index — run converge) and blocked items (NOT NULL pending backfill — manual action needed).
- Should convergence in dev mode skip CONCURRENTLY for speed? **Resolved: yes.** No concurrent traffic in dev, and regular `CREATE INDEX` is faster and simpler (runs inside a transaction, no two-phase build). Detection via `DEBUG=True` or `--dev` flag on the converge command.
- How to handle indexes with the same columns but different names? (e.g., convergence wants `users_email_idx`, DB has `idx_users_email` from manual creation on the same columns) **Unresolved.** Convergence should report duplicate-column indexes as informational in `postgres schema` output. It should never drop an index it doesn't own. The developer can manually drop the legacy index or rename it to match the model declaration. Could offer a `postgres adopt-index` command in the future.

## Research references

Research conducted across declarative schema tools, Postgres internals, and production migration safety gems to inform the convergence ordering, backfill safety, and `db_default` decisions above.

### Postgres internals (lock levels and behavior)

All lock levels confirmed against the [PostgreSQL 18 ALTER TABLE documentation](https://www.postgresql.org/docs/current/sql-altertable.html):

- **SET DEFAULT / DROP DEFAULT**: ACCESS EXCLUSIVE lock, but catalog-only — completes in milliseconds, no table scan, no rewrite. "The new default value will only apply in subsequent INSERT or UPDATE commands; it does not cause rows already in the table to change."
- **SET NOT NULL**: ACCESS EXCLUSIVE lock. Scans entire table to verify no NULLs exist, _unless_ a valid CHECK constraint proves it unnecessary: "if a valid CHECK constraint is found which proves no NULL can exist, then the table scan is skipped." This is the foundation of the CHECK-then-SET-NOT-NULL pattern.
- **ADD CONSTRAINT ... NOT VALID**: Skips the validation scan. For FK constraints, takes SHARE ROW EXCLUSIVE. For CHECK constraints, ACCESS EXCLUSIVE but instant (no scan).
- **VALIDATE CONSTRAINT**: SHARE UPDATE EXCLUSIVE lock — does not block reads or writes. "The validation step does not need to lock out concurrent updates, since it knows that other transactions will be enforcing the constraint for rows that they insert or update."
- **ADD CONSTRAINT ... USING INDEX**: Requires an existing unique b-tree index with default sort ordering, not partial, no expression columns. Instant operation — the index is "owned" by the constraint afterward.
- **ADD COLUMN with non-volatile DEFAULT** (PG 11+): Catalog-only, stores default in `pg_attribute.attmissingval`. No table rewrite. Volatile defaults (e.g., `random()`, `now()`) still require a rewrite.

### Declarative schema tools

- **Stripe's pg-schema-diff** ([github.com/stripe/pg-schema-diff](https://github.com/stripe/pg-schema-diff)): The closest prior art to Plain's convergence. Declarative Postgres schema diffing — you define desired state as SQL DDL, it diffs against the live DB, generates an ordered plan, and applies with safe DDL. Implements every pattern convergence uses: CONCURRENTLY for indexes, online index replacement (rename old → build new → drop old), NOT NULL via CHECK dance, FK/CHECK constraints via NOT VALID + VALIDATE. Per-statement `lock_timeout` (3s default) AND `statement_timeout` (3s default, 20min for index builds). A hazard system that **refuses to apply** unless you explicitly `--allow-hazards INDEX_BUILD,DELETES_DATA` — a gate, not a warning. Uses topological sort with priority-based tie-breaking for operation ordering. Renames explicitly unsupported (names are identity, same as convergence). MIT licensed, production-proven at Stripe scale.
- **Atlas**: Generates migration plans by diffing desired schema against current DB state. Uses diff policies to control concurrent index creation. For unique constraints, requires a two-phase approach: create unique index concurrently first, then convert to constraint via `USING INDEX`. Plan structure (not a dependency graph) enforces ordering. 50+ safety analyzers detect destructive changes, table locks, and data loss risks.
- **Prisma**: `db push` applies schema directly for prototyping; `migrate dev` generates migration files. No auto-backfill — adding a required column to a table with existing rows fails with an error. No safe DDL patterns (no CONCURRENTLY, no NOT VALID). Defaults are handled at the Prisma client level, not as `db_default`.
- **pgroll**: Expand/contract pattern with dual-schema access during migration. Backfills in batches of 1,000 rows (configurable), with configurable inter-batch delay. v0.7.0 added batch size/delay configuration and 80% performance improvements to backfills.
- **PlanetScale**: Their MySQL/Vitess product has deploy requests, safe DDL via ghost tables, schema diffing, and zero-downtime cutover. Their Postgres product (GA Sep 2025) has branching but **none** of the safe DDL features — no deploy requests, no automated schema changes, no linting. For Postgres, you handle schema safety yourself. This gap is exactly what Plain's convergence fills at the framework level.

### Rails ecosystem safety tools

- **strong_migrations**: Detects unsafe operations and provides safe alternatives. Recommends batches of 10,000 rows with `sleep()` throttling for backfills, always outside a transaction. No built-in row count threshold — uses qualitative guidance ("you probably don't need this gem for smaller projects"). Safe NOT NULL pattern: add CHECK constraint NOT VALID, validate in separate migration, then SET NOT NULL.
- **safe-pg-migrations**: Automatically rewrites unsafe migrations to safe equivalents. Default backfill batch size of 100,000 rows with 0.5s pause. Has an optional `default_value_backfill_threshold` config — migrations fail if table exceeds configured row count. Lock timeout default of 5s with retry logic (5 attempts).
- **pg_ha_migrations**: `safe_make_column_not_nullable` uses CHECK constraint approach. `safe_add_foreign_key` adds NOT VALID first, validates separately. `safe_change_column_default` handles constant and functional defaults. On PG 11+, enforces single-step column addition with constant defaults.

### Django autodetector ordering

Django's `MigrationAutodetector` uses a fixed generation order (not a dependency graph) for operation _types_: renames first, then deletes, creates, field operations, and finally indexes/constraints. Within an app, it uses `TopologicalSorter` from `graphlib` to resolve intra-app dependencies (e.g., FK field depends on target model existing). The generation order is: `generate_removed_constraints` → `generate_removed_indexes` → `generate_removed_fields` → `generate_added_fields` → `generate_altered_fields` → `generate_added_indexes` → `generate_added_constraints`. This is analogous to the multi-pass approach — fixed type ordering with dependency resolution only where truly needed.
