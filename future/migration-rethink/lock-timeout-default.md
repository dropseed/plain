# Set lock_timeout on all migration DDL

## Problem

When a migration runs `ALTER TABLE`, it requests an ACCESS EXCLUSIVE lock. If a long-running query holds ACCESS SHARE on that table, the migration waits. While it waits, every new query on that table queues behind the ACCESS EXCLUSIVE request. A DDL statement that would take 1ms to execute can cause a minutes-long outage because of the lock queue cascade.

Django/Plain never sets `lock_timeout`, so this wait is unbounded.

## Solution

Set `lock_timeout` before every DDL statement in the schema editor. Default to something reasonable (e.g., 4 seconds). If the lock can't be acquired, fail fast with a clear error instead of silently blocking the application.

```sql
SET lock_timeout = '4s';
ALTER TABLE orders ADD COLUMN status varchar(255);
SET lock_timeout = '0';  -- restore
```

Configurable via a setting (e.g., `POSTGRES_MIGRATION_LOCK_TIMEOUT`).

## Why this is first

Smallest change, biggest safety improvement. One-line addition to the schema editor with massive impact. No workflow changes, no new concepts. Works with the existing migration system — doesn't depend on convergence or any other future in this arc.

## `statement_timeout` too

`lock_timeout` prevents waiting for a lock. `statement_timeout` prevents a statement that acquired the lock from running too long. Both should be set per-statement.

Most DDL is instant (catalog-only), but `CREATE INDEX CONCURRENTLY` and `VALIDATE CONSTRAINT` can take minutes on large tables. These need a longer `statement_timeout` than regular DDL.

```sql
-- Regular DDL: short timeouts
SET lock_timeout = '4s';
SET statement_timeout = '4s';
ALTER TABLE orders ADD COLUMN status varchar(255);

-- Index builds: short lock timeout, long statement timeout
SET lock_timeout = '4s';
SET statement_timeout = '20min';
CREATE INDEX CONCURRENTLY orders_status_idx ON orders (status);
```

Default timeouts per operation type (following pg-schema-diff's production-proven defaults):

| Operation                                            | lock_timeout | statement_timeout |
| ---------------------------------------------------- | ------------ | ----------------- |
| Regular DDL (ALTER TABLE, SET DEFAULT, SET NOT NULL) | 4s           | 4s                |
| CREATE/DROP INDEX CONCURRENTLY                       | 4s           | 20min             |
| VALIDATE CONSTRAINT                                  | 4s           | 20min             |
| Table/column drops                                   | 4s           | 20min             |

Configurable via settings: `POSTGRES_LOCK_TIMEOUT`, `POSTGRES_STATEMENT_TIMEOUT`, `POSTGRES_INDEX_STATEMENT_TIMEOUT`.

## Considerations

- Per-statement timeouts, not per-migration. Each statement gets its own timeout based on the operation type.
- Convergence operations that use SHARE UPDATE EXCLUSIVE (CONCURRENTLY, VALIDATE) are much less likely to be blocked, but should still have a lock_timeout for safety.
- The migration runner could retry with backoff on lock timeout failures, rather than just failing.

## Prior art

Stripe's [pg-schema-diff](https://github.com/stripe/pg-schema-diff) uses the same per-statement timeout pattern: 3s defaults for regular DDL, 20min for index builds and drops. These defaults are production-tested at Stripe scale.
