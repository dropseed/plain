# Failure handling

## The key insight

The migration/convergence split naturally gives each system the right failure semantics. Migrations get transactional rollback (because they no longer contain non-transactional operations). Convergence gets graceful degradation (because each operation is independent and idempotent).

## Migrations: batch transaction, all-or-nothing

Slim migrations contain only catalog-only DDL (AddField, RemoveField, CreateModel, RenameField) and data operations (RunPython). All of these work perfectly in transactions. A batch of slim migrations takes milliseconds of lock time.

```
$ plain postgres sync

Migrations:
  ✓ 20240301_140000 create_orders
  ✓ 20240315_110000 add_priority_field
  ✗ 20240320_090000 backfill_priority — ERROR: division by zero
  ↩ Rolled back all 3 migrations. Database unchanged.
```

If any migration in the batch fails, everything rolls back. The database is in the exact state it was before `sync` started. No partial migration state, no manual recovery needed. Fix the issue, re-deploy.

This is the same as today's behavior — but without the downsides. Today, the batch transaction also contains slow operations (CREATE INDEX, VALIDATE CONSTRAINT) that hold ACCESS EXCLUSIVE locks for the entire batch duration. In the slim model, those operations aren't in migrations at all.

## Convergence: per-operation, retry on failure

Convergence is non-transactional by design (CONCURRENTLY can't run in a transaction). Each operation is independent:

```
$ plain postgres sync

Schema convergence:
  ✓ orders — created index orders_user_id_idx
  ✓ orders — created FK constraint orders_author_fk
  ✗ orders — index orders_priority_idx failed (lock_timeout)
  ⏸ orders.priority — NOT NULL blocked (3 rows have NULLs)
```

A failed convergence operation is not a deploy failure. The application works — a missing index means slower queries, not broken code. An unvalidated FK means new rows are checked but old data isn't proven valid yet.

Run `postgres sync` again later to retry. Convergence checks the current state each time, so it picks up where it left off.

## Why this is better than today

Today the framework has two bad options:

**`atomic=True`** (default): Safe rollback, but transactions prevent CONCURRENTLY and VALIDATE CONSTRAINT from working. Locks are held for the entire migration including slow index builds. The safe DDL patterns are impossible.

**`atomic=False`**: Enables safe DDL patterns, but partial failure leaves the database in an unrecoverable state — migration half-applied, not recorded, can't re-run cleanly. Django's recommendation is "put each non-atomic operation in its own migration file," which is fragile and error-prone.

The split eliminates this tradeoff:

|               | Migrations                           | Convergence                                    |
| ------------- | ------------------------------------ | ---------------------------------------------- |
| Transaction   | Batch — all or nothing               | Per-operation — each independent               |
| On failure    | Roll back everything, clean state    | Skip, report, retry next run                   |
| Deploy impact | Deploy fails, old code stays running | Deploy succeeds, schema partially converged    |
| Recovery      | Fix issue, re-deploy                 | Run `postgres sync` again                      |
| Lock duration | Milliseconds (catalog-only DDL)      | Per-operation (CONCURRENTLY holds light locks) |

## Convergence skips if migrations fail

If migrations fail and roll back, convergence should not run. The schema may be in a state where convergence actions don't make sense (e.g., trying to add an index on a column that was going to be added by the failed migration).

`postgres sync` runs migrations first. If migrations fail, it stops and reports. Convergence only runs after migrations succeed.

## Long-running RunPython

A `RunPython` that backfills 1M rows inside the batch transaction holds the transaction open. This prevents VACUUM and maintains a long-lived snapshot. For small backfills this is fine. For large ones:

- The RunPython function can manage its own cursor and commit in batches, operating outside the migration framework's transaction for the data work
- Or: design a convention where large backfills are marked to run outside the batch transaction (like a `run_outside_transaction = True` flag)
- Or: rely on the developer to structure large backfills appropriately (same as today)

This is an existing concern, not a new one introduced by the rethink. The slim migration model doesn't make it worse.

## Convergence failure modes in detail

### INVALID indexes

`CREATE INDEX CONCURRENTLY` can fail (lock_timeout, deadlock, duplicate key for unique indexes) and leave an INVALID index. An INVALID index:

- Imposes write overhead (Postgres maintains it on every insert/update)
- Is never used for queries
- Blocks future `CREATE INDEX CONCURRENTLY IF NOT EXISTS` from working (it silently succeeds, thinking the index exists)

Convergence must: check `pg_index.indisvalid` before and after creation. If INVALID, drop and retry.

### Unvalidated constraints

`ADD CONSTRAINT FK NOT VALID` succeeds, then `VALIDATE CONSTRAINT` fails (e.g., orphaned FK reference). The constraint exists but isn't validated:

- New inserts/updates are checked (immediate correctness)
- Old data isn't proven valid
- This is a safe intermediate state

Next convergence run retries VALIDATE. The data issue (orphaned reference) must be fixed before it can succeed.

### lock_timeout on convergence operations

Even CONCURRENTLY and VALIDATE can hit lock_timeout (they take SHARE UPDATE EXCLUSIVE, which self-conflicts). If convergence hits a timeout:

- The operation didn't happen (no partial state)
- Report it, retry next run
- This usually means another convergence or VACUUM is running on the same table

### Multiple convergence operations fail

Convergence creates 3 of 5 indexes, fails on 2. The 3 successful ones are committed. Next run: convergence sees 3 exist, retries the 2 that failed. No accumulated state to clean up.

## Deploy rollback

The sections above cover _migration failure_ (batch transaction rolls back) and _convergence failure_ (retry next run). But there's a third failure mode: the deploy itself succeeds, migrations and convergence run cleanly, and then the **application code** has a bug. You need to roll back to the previous code version.

This is the hardest problem in schema management, and the industry has largely converged on one answer: **don't reverse the schema, fix forward.**

### Why reverse schema migrations don't work

The scenario: convergence applied `NOT NULL` on `orders.status`. Old code writes NULL to that column in some edge case. You roll back to old code. Old code starts failing on INSERT.

The traditional answer is "run the down migration to remove the NOT NULL." Every framework that supports this has found it doesn't work in practice:

- **Django**: An audit of 666 Django projects found 22% have at least one irreversible migration. `RunPython` operations often lack reverse functions. Even when reverse migrations exist, they're rarely tested and frequently broken.
- **Rails**: `db:rollback` exists but the Rails guides emphasize writing reversible migrations as a best practice — an acknowledgment that many aren't. Production rollback is manual and risky.
- **Ecto**: Provides `mix ecto.rollback` with explicit `up`/`down` functions. The Elixir community's guidance is to keep migrations small and focused so rollback is tractable, but production rollback is still uncommon.
- **Laravel**: `migrate:rollback` works per-batch. Teams are warned to test rollback in staging first. In practice, it's a development tool — production rollback is a last resort.
- **Prisma**: Forward-only by design. `prisma migrate deploy` has no built-in reverse. Down migrations must be manually generated with `prisma migrate diff`, manually applied with `db execute`, and manually recorded with `migrate resolve`. The official guidance is "rolling forward is much more attractive than rolling back."
- **Flyway**: The community edition has no undo capability at all. The paid edition added undo migrations, but Redgate's own documentation recommends rolling forward for production: "when reverting database schema changes made to any live production database, it is simpler to roll forward."
- **Atlas**: Explicitly distinguishes rollback (transaction-level, automatic) from down migrations (schema reversion, deliberate). Their `migrate down` command computes reversals dynamically rather than relying on pre-written scripts — an acknowledgment that pre-written down migrations are unreliable.

The consensus is clear: reverse schema migrations are a development convenience, not a production safety mechanism. Every framework that offers them also documents why you shouldn't rely on them.

### Why convergence makes reverse migrations worse, not better

In a traditional migration system, you _could_ write a reverse migration that removes a NOT NULL constraint. With convergence, you can't — convergence sees the model still declares `NOT NULL` (on the new code) or sees the NOT NULL as "unmanaged" (on the old code) and either re-applies it or ignores it. There's no migration file to reverse.

This sounds like a regression, but it's actually clarifying the truth. Reverse migrations were already broken — convergence just makes that visible. The real problem was never "how do I undo the schema change" but "how do I make schema changes that don't break old code."

### The answer: expand and contract

The expand and contract pattern (sometimes called "parallel change") is the industry-standard approach for schema changes that need to coexist with multiple code versions. It breaks a dangerous change into safe phases:

**Expand** — add the new thing without removing or restricting the old thing. Both code versions work.

**Migrate** — move data and application logic to use the new structure. Old code still works.

**Contract** — remove the old thing once all code is on the new version.

For the `NOT NULL` example:

1. **Deploy 1 (expand)**: Add the column as nullable. Convergence skips NOT NULL (NULLs exist from old code). New code writes non-NULL values.
2. **Deploy 2 (migrate)**: Backfill old NULLs. New code is the only code running. Convergence sees zero NULLs, applies NOT NULL.
3. No "contract" step needed — the constraint is the final state.

At every point in this sequence, rolling back to the previous deploy is safe because the schema is backward-compatible with the previous code.

This is exactly how the "Rolling deploys and NOT NULL" section in schema-convergence.md already works. Convergence's "check before acting" behavior is expand-and-contract by default — it won't apply NOT NULL while NULLs exist, it won't validate a FK while orphans exist.

**pgroll** (Xata's Postgres schema migration tool) automates this pattern with versioned views and triggers, allowing old and new code to see different schema versions simultaneously. Plain's convergence model is simpler — it doesn't use views or triggers — but the principle is the same: schema changes are always additive until old code is fully drained.

### What this means for Plain

**No reverse migrations. No `--rollback` flag on convergence. No `postgres migrate down`.** This is a deliberate design choice, not a gap.

The justification:

1. **Industry precedent**: Prisma and Flyway (community) are forward-only and successful. Atlas computes reversals dynamically rather than relying on pre-written scripts. The trend is away from reverse migrations.
2. **Convergence is inherently forward**: it compares desired state to actual state and applies the difference. "Reverse" would mean "make the database match a _previous_ desired state," which requires knowing what that state was — exactly the historical state tracking we're eliminating.
3. **Expand-and-contract is the real answer**: If a schema change can break old code, it should be phased across deploys. Convergence's check-before-acting behavior naturally supports this.
4. **Emergency escape hatch**: If you absolutely must undo a convergence-applied constraint, use `RunSQL` in a new migration or run SQL directly. This is explicit, auditable, and doesn't pretend the framework can safely automate reversal.

### Guidance for developers

The docs should be clear about the deploy rollback story:

- **Schema changes that restrict** (NOT NULL, new constraints, dropping columns) must be deployed _after_ all code handles the restriction. This is the "contract" phase — it happens in a separate deploy from the code change.
- **Schema changes that expand** (new nullable columns, new tables, new indexes) are always safe to roll back from because old code ignores them.
- **If you need to undo a convergence operation in an emergency**, write a forward migration with `RunSQL` that drops the constraint. Then fix the model to match. This is the "fix forward" pattern.
- **Convergence reports pending operations** for a reason — `NOT NULL blocked (3 rows have NULLs)` is the system telling you the expand phase isn't complete. Don't force it.
