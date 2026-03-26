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

## Considerations

- Convergence operations that use SHARE UPDATE EXCLUSIVE (CONCURRENTLY, VALIDATE) are much less likely to be blocked, but should still have a timeout for safety.
- Should the timeout be per-statement or per-migration? Per-statement is simpler and safer.
- The migration runner could retry with backoff on lock timeout failures, rather than just failing.
