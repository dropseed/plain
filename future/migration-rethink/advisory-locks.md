# Advisory locks for migration coordination

## Problem

The current migration system locks the `plain_migrations` table with `SHARE UPDATE EXCLUSIVE` to prevent concurrent migration runs. This lock lives inside a transaction, which means:

1. The lock is held for the entire migration transaction duration
2. `CREATE INDEX CONCURRENTLY` can't run inside the transaction
3. `VALIDATE CONSTRAINT` can't run inside the transaction
4. Any non-transactional operation is incompatible with the migration lock

## Solution

Use `pg_advisory_lock` on a separate connection (session-level, not transaction-bound) to coordinate `postgres sync` and other schema-changing commands. This decouples the "only one schema writer at a time" guarantee from the DDL transaction.

```python
# Connection 1: hold advisory lock
SELECT pg_try_advisory_lock(78770566);  -- fixed key

# Connection 2: run migration DDL (can be non-transactional)
CREATE INDEX CONCURRENTLY ...;

# Connection 1: release advisory lock
SELECT pg_advisory_unlock(78770566);
```

This is what Ecto added in v3.9. It unblocks non-transactional DDL while maintaining the single-writer guarantee.

## One sync lock

The earlier idea of separate migration and convergence locks was too clever. `postgres sync` is a single contract: "make the database match the current code." If one process is still applying migrations while another is already converging, the second process can act on stale assumptions and report misleading success.

Use one advisory lock for any schema-changing command (`postgres sync`, `migrations apply`, `postgres converge`). That keeps the behavior obvious:

- Process A running `postgres sync` blocks Process B from starting another schema-changing command
- No node can converge against pre-migration state while another node is still migrating
- Index creation races and INVALID index traps are avoided because convergence is serialized too

This is slightly more restrictive than separate locks, but the clarity is worth it. If performance-only convergence later proves worth parallelizing, that can be an explicit future optimization rather than the default contract.

### Lock key selection rationale

Fixed integer constants, not hashed strings.

- **78770566** for sync/schema changes (the value already in Plain's codebase, carried forward)

Why not hash the database name (like Rails) or the repo module (like Ecto)?

- Plain targets a single database per project. No multi-database disambiguation needed.
- Fixed constants are debuggable. `SELECT * FROM pg_locks WHERE objid = 78770566` immediately tells you what's happening.
- The two-integer advisory lock variant (`pg_advisory_lock(classid, objid)`) could namespace by "plain" in the first 32 bits, but single-int is simpler and sufficient for one lock.

If Plain ever supports multiple databases per project, the key generation should incorporate the database identifier -- but that's a bridge to cross then.

## Lock behavior: non-blocking with retry

Use `pg_try_advisory_lock` (non-blocking), not `pg_advisory_lock` (blocking).

The blocking variant hangs indefinitely if the lock holder crashes without releasing. The non-blocking variant returns immediately with `true`/`false`, letting the caller control retry behavior.

```python
acquired = cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY]).fetchone()[0]
if not acquired:
    # another process is running, wait and retry
```

### Retry settings

| Setting        | Default            | Rationale                                                                                                                        |
| -------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Retry interval | 5 seconds          | Long enough to avoid busy-waiting, short enough to notice when the lock clears                                                   |
| Max retries    | 720 (1 hour total) | Full syncs can legitimately hold the lock during long index builds. Wait for the active schema writer rather than failing early. |

Configurable via settings: `POSTGRES_SYNC_LOCK_RETRY_INTERVAL_MS` and `POSTGRES_SYNC_LOCK_MAX_RETRIES`.

On max retries exceeded: fail with a clear error message including the PID of the lock holder (queryable from `pg_locks`).

### Why not blocking?

Rails uses `pg_advisory_lock` (blocking) and has been bitten: if a migration process crashes or is killed, the session may not close cleanly (especially through PgBouncer), leaving the lock held. The next process hangs forever. Rails added `advisory_locks: false` as a database config escape hatch -- evidence that the blocking approach causes real operational pain.

Ecto uses `pg_try_advisory_lock` with retry (5s interval, infinite retries by default). We follow Ecto's pattern but cap retries -- infinite retry still hangs when the holder is dead.

## PgBouncer

Session-level advisory locks are incompatible with PgBouncer's transaction pooling mode. In transaction mode, each SQL statement can land on a different server connection, so a lock acquired on one statement may be invisible to the next.

### Guidance for PgBouncer users

**Option 1 (recommended): Direct connection for migrations.** Run `postgres sync` with a direct connection to PostgreSQL, bypassing PgBouncer entirely. Migrations are an admin operation, not a request-serving path. Most deployment setups already have access to the direct connection string.

Configure via `DATABASE_URL` override at deploy time:

```bash
DATABASE_URL=postgres://user:pass@db-host:5432/mydb plain postgres sync
```

**Option 2: Session pooling pool.** Run a separate PgBouncer pool in session mode for admin operations. Route migration commands to this pool. This is the pattern PgBouncer's own docs recommend for session-dependent features.

**Option 3: Disable locking.** If you guarantee single-writer at the deployment level (e.g., a single deploy job, not multiple concurrent processes), you can disable the advisory lock entirely. This is a last resort -- the lock exists because "I promise only one thing runs schema changes" is a guarantee that breaks silently.

We will NOT attempt workarounds like `server_reset_query_always` or transaction-level advisory locks (`pg_advisory_xact_lock`). Transaction-level locks re-introduce the original problem: the lock is bound to a transaction, preventing non-transactional DDL. Flyway tried both approaches and the result is a maze of configuration flags and known issues.

## Connection requirements

Advisory lock acquisition requires a dedicated connection separate from the DDL connection:

```
Connection A (lock holder):
  pg_try_advisory_lock(78770566) -> true
  ... holds connection open ...
  pg_advisory_unlock(78770566)

Connection B (worker):
  BEGIN;
  ALTER TABLE ... ;
  INSERT INTO plain_migrations ... ;
  COMMIT;
  -- or, for convergence:
  CREATE INDEX CONCURRENTLY ... ;
```

This means `postgres sync` needs at least two database connections. Document this requirement clearly -- connection pool minimum size must be >= 2 when running migrations.

Plain already uses a similar pattern in `plain.jobs.locks` (advisory locks via `pg_advisory_xact_lock`), so the connection infrastructure exists.

## Implementation sketch

```python
@contextmanager
def advisory_lock(lock_key: int, cursor_factory) -> Iterator[None]:
    """
    Acquire a session-level advisory lock with retry.
    Uses a dedicated connection (cursor_factory) separate from the DDL connection.
    """
    max_retries = settings.POSTGRES_SYNC_LOCK_MAX_RETRIES  # default 720
    retry_interval = settings.POSTGRES_SYNC_LOCK_RETRY_INTERVAL_MS / 1000  # default 5s

    with cursor_factory() as cursor:
        for attempt in range(max_retries):
            row = cursor.execute(
                "SELECT pg_try_advisory_lock(%s)", [lock_key]
            ).fetchone()
            if row[0]:
                try:
                    yield
                finally:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_key])
                return
            time.sleep(retry_interval)

        # Failed to acquire after all retries
        holder_info = _get_lock_holder_info(cursor, lock_key)
        raise MigrationLockTimeout(
            f"Could not acquire sync lock after {max_retries} retries "
            f"({max_retries * retry_interval:.0f}s). Lock holder: {holder_info}"
        )


SYNC_LOCK_KEY = 78770566
```

## Industry comparison

### How other frameworks coordinate concurrent migrations

| Framework         | Mechanism                                          | Lock type         | PgBouncer compatible        | Non-transactional DDL                  |
| ----------------- | -------------------------------------------------- | ----------------- | --------------------------- | -------------------------------------- |
| **Ecto** (v3.9+)  | `pg_advisory_lock` (opt-in)                        | Session-level     | No (session mode required)  | Yes (the whole point)                  |
| **Rails** (5.2+)  | `pg_advisory_lock` (default)                       | Session-level     | No (can disable via config) | No (not designed for it)               |
| **Django**        | Table lock (`SHARE UPDATE EXCLUSIVE`)              | Transaction-bound | Yes                         | No                                     |
| **Laravel**       | Cache-based atomic lock (`--isolated`)             | Application-level | Yes                         | No                                     |
| **Flyway** (9.1+) | `pg_advisory_xact_lock` (default) or session-level | Configurable      | Transaction lock only       | Session lock required for CONCURRENTLY |
| **Liquibase**     | `DATABASECHANGELOGLOCK` table                      | Row-level flag    | Yes                         | No                                     |
| **Atlas**         | Named advisory lock (`atlas_migrate_execute`)      | Session-level     | Not documented              | Yes                                    |

### Key patterns and lessons

**Ecto** got this right first. Session-level advisory lock, opt-in to avoid breaking PgBouncer users, retry with configurable interval. Lock key is a hash of `{:ecto, prefix, repo}` via `:erlang.phash2`. The design explicitly enables `CREATE INDEX CONCURRENTLY` outside the lock's transaction. Retry defaults: 5s interval, infinite retries.

**Rails** uses advisory locks by default since 5.2. Key is `MIGRATOR_SALT * CRC32(database_name)`. Raises `ConcurrentMigrationError` on conflict. Known problem: doesn't include schema name, so multi-tenant setups with separate schemas can't migrate in parallel. PgBouncer in transaction mode causes `ConcurrentMigrationError` on every migration -- Rails added `advisory_locks: false` as an escape hatch in Rails 6.

**Django** has no advisory lock support. It locks the `django_migrations` table inside the migration transaction. This means the lock is held for the entire migration duration including slow operations. Third-party libraries (`django-pglock`, `django-pg-zero-downtime-migrations`) add advisory lock wrappers, but they're bolt-ons, not integrated into the migration executor. Django's approach is the simplest but the least capable -- it prevents both concurrent migrations AND non-transactional DDL.

**Laravel** doesn't use database-level locking at all. The `--isolated` flag uses cache-based atomic locks (Redis, Memcached, etc.), which means the locking depends on a separate infrastructure component and doesn't survive cache failures. Fine for simple cases, fragile for anything serious.

**Flyway** has the most complex story. v9.1.2 introduced `pg_advisory_xact_lock` as the default (transaction-level). This immediately broke `CREATE INDEX CONCURRENTLY` because the lock is transaction-bound. They added `postgresql.transactional.lock=false` to switch to session-level locks. The result: two config flags, confusing defaults, and multiple open issues. This is exactly the mess we're avoiding by choosing session-level from the start.

**Liquibase** uses a `DATABASECHANGELOGLOCK` table with a `LOCKED` boolean column. Known failure mode: if the process is killed mid-migration, the row stays locked. Manual intervention required (`liquibase release-locks` or direct SQL `UPDATE ... SET locked=false`). The 5-minute default wait timeout means deployments hang for 5 minutes before failing when a stale lock exists. Advisory locks don't have this problem -- they auto-release when the session ends.

**Atlas** uses named advisory locks (default name `atlas_migrate_execute`). Supports `--lock-name` for multi-app databases and `--lock-timeout` (default 10s). The naming approach is interesting but relies on hashing the name to an integer internally. Atlas Pro feature, not available in the open-source version.

### What we take from this

1. **Session-level advisory lock** (Ecto, Rails, Atlas) -- not transaction-level (Flyway's mistake) or table-level (Django, Liquibase).
2. **Non-blocking with retry** (Ecto) -- not blocking (Rails' operational pain) or table flag (Liquibase's stale lock problem).
3. **Fixed key constants** -- simpler than hash-based (Rails' CRC32, Ecto's phash2) since we don't need multi-database support.
4. **One schema-writing lock** -- clearer contract than trying to overlap migrations and convergence.
5. **Direct connection for PgBouncer** -- the only clean solution. Don't try to make session features work through transaction pooling.
