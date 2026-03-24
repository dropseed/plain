---
related:
  - db-connection-pool
---

# plain-postgres: psycopg3 features

Now that Plain is PostgreSQL-only, we should lean into psycopg3's native capabilities — both to gain features and to remove abstraction that existed for multi-DB compatibility.

## Remove abstraction / lean on psycopg3

### Server-side cursors → `cursor.stream()`

Currently `chunked_cursor()` creates a named cursor with a manually generated unique name (`_plain_curs_{thread}_{task}_{idx}`), then `cursor_iter()` calls `fetchmany(itersize)` in a loop with a sentinel value `[]` hardcoded as "empty_fetchmany_value for PostgreSQL" — a multi-DB fossil.

psycopg3's `cursor.stream(query, params)` replaces all of that with a lazy generator over server-side results. The "must fully consume" caveat is a non-issue since the current code already uses `try/finally: cursor.close()`.

Removes: `chunked_cursor()`, `cursor_iter()`, named cursor index tracking, sentinel value.

### Savepoint SQL → `connection.transaction()`

Currently `_savepoint()`, `_savepoint_rollback()`, `_savepoint_commit()` execute raw SQL strings plus manual savepoint ID generation with thread ident formatting.

psycopg3's `connection.transaction()` handles nested savepoints natively. The `Atomic` class can't be fully replaced — it manages `needs_rollback` propagation, on-commit hooks, `closed_in_transaction`, durable block validation — but it could use `connection.transaction()` internally instead of issuing raw SQL and managing IDs. The state tracking stays, the SQL mechanics go away.

This is a meaningful refactor, not a drop-in swap.

### `connection.execute()` for internal one-off queries

psycopg3 connections can execute queries directly without creating an explicit cursor. Some internal operations (savepoint SQL, `SET ROLE`, `SELECT 1` health check) create cursors just to run one statement. Minor cleanup.

### ~~Exception hierarchy~~ ✓

Done — PEP-249 mirror and `DatabaseErrorWrapper` removed. psycopg exceptions propagate directly. `errors_occurred` flag replaced with `connection.closed` check.

### Row factories for `values()` / `values_list()`

psycopg3's `dict_row` and `namedtuple_row` cursor row factories could simplify `values()` and `values_list(named=True)`. Currently the ORM manually builds dicts/namedtuples from tuples. Using row factories would let psycopg3 handle that. Code simplification even if perf is neutral.

## New capabilities

### Prepared statements — enable by default

ORMs repeat the same query shapes constantly — automatic preparation avoids repeated parse/plan cycles. With in-process psycopg_pool (no external pooler), `prepare_threshold=5` is safe — psycopg3 tracks prepared statements per-connection and the pool manages the same connections.

PgBouncer caveat: prepared statements work through PgBouncer only with PgBouncer 1.22+ and client-side support for `send_close_prepared` (check via `psycopg.Capabilities.has_send_close_prepared()`). Users without this who use PgBouncer must set `prepare_threshold: null` in `POSTGRES_OPTIONS`.

Options: enable by default and document the PgBouncer caveat, or keep disabled by default and make it easy to enable. Meaningful perf win when enabled.

### Pipelines for `prefetch_related()`

`prefetch_related()` fires N independent queries sequentially. Wrapping them in `connection.pipeline()` batches into fewer round trips. This is the one place in the ORM where independent queries are issued in a known pattern.

Requires client-side pipeline support — check `psycopg.Capabilities.has_pipeline` at runtime rather than enforcing a libpq version. Note: psycopg3 docs describe pipeline mode as **experimental**, with caveats around error handling and concurrency. Cannot be used with COPY, `cursor.stream()`, or server-side cursors.

### COPY for bulk inserts

`cursor.copy()` with `write_row()` is significantly faster than `INSERT ... VALUES` for large datasets. Limitation: no RETURNING and no ON CONFLICT. Could be a fast path in `bulk_create()` when those aren't needed, or exposed as a separate `bulk_copy()` method so intent is clear.

### `executemany(returning=True)`

Currently bulk inserts with RETURNING build a single `INSERT ... VALUES (...), (...), ... RETURNING ...`. `executemany(returning=True)` pipelines individual INSERT statements instead. Current approach may already be efficient, but `executemany(returning=True)` might simplify the batching code. Worth benchmarking.

### Binary wire format

`binary=True` on cursor/execute returns results in PostgreSQL binary format, skipping text parsing for types like integers, floats, UUIDs, dates. All-or-nothing per query (not per-column). For input parameters, `%b` forces binary per-parameter. Worth benchmarking for read-heavy workloads.

### `NullConnectionPool` option

`psycopg_pool.NullConnectionPool` creates connections on-demand and closes on return, same API as `ConnectionPool`. Useful for serverless where persistent pools don't make sense. Low effort to offer as a setting.

### LISTEN/NOTIFY

psycopg3's `connection.notifies()` consumes PostgreSQL notifications. Not actionable today but could enable event-driven patterns in `plain-jobs` (notify on job insert instead of polling) and underpin future real-time features.
