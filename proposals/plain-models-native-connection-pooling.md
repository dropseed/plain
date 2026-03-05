# plain-models: Native Connection Pooling

- Add native PostgreSQL connection pooling via `psycopg_pool.ConnectionPool`
- Eliminates need for PgBouncer in most deployments
- Django added this in 5.1 (PR #17914, ticket #33497) — motivated by ASGI breaking `CONN_MAX_AGE`

## Why native pooling over PgBouncer

- **Connection setup cost**: TCP + TLS + auth = 50-70ms per request on cloud Postgres; native pooling eliminates this for ~5x throughput improvement on simple endpoints
- **No session state issues**: PgBouncer transaction pooling breaks prepared statements, `SET ROLE`, `SET timezone`, server-side cursors; native pooling preserves full session semantics
- **Zero infrastructure**: no separate daemon, config, monitoring, or failure point
- **No extra network hop**: connection checkout is a function call, not a proxy round-trip

## Where PgBouncer still wins

- Multi-service architectures sharing one Postgres instance (cross-process multiplexing)
- High-scale deployments needing to multiplex N workers × pool_size down to fewer backend connections
- Plain's native pool is per-process, so total connections = workers × max_size

## Implementation (following Django 5.1)

- Add `POSTGRES_POOL` setting (bool or dict of psycopg_pool options like `min_size`, `max_size`, `timeout`)
- Incompatible with `POSTGRES_CONN_MAX_AGE != 0` — raise `ImproperlyConfigured`
- Pool uses `configure` callback to run `_configure_timezone` and `_configure_role` on each checkout
- `init_connection_state` skips configure when pooling (pool's callback handles it)
- `_close()` calls `putconn()` instead of `connection.close()` when pooling
- `ensure_timezone()` destroys the pool when timezone changes so new connections get the correct setting
- Requires `psycopg[pool]` or `psycopg-pool` package

## Managed Postgres services (Neon, Supabase, etc.)

- These services often run their own PgBouncer-style pooler server-side
- Native pooling is complementary — avoids per-request TCP/TLS to the service's pooler endpoint
- Users need guidance on sizing: 8 workers × max_size 4 = 32 connections against a 60-connection limit
- Document interaction with service-level pooling and connection limits

## Existing PgBouncer compatibility (separate concern)

- Prepared statements already disabled by default (`prepare_threshold = None`)
- Should also add `DISABLE_SERVER_SIDE_CURSORS` equivalent (or `POSTGRES_DISABLE_SERVER_SIDE_CURSORS` setting) for users who still use PgBouncer
- `SET ROLE` via `assume_role` is session-scoped and undocumented as incompatible with PgBouncer transaction pooling — should document this
