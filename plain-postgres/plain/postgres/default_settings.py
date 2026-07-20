from os import environ

from plain.runtime.secret import Secret

# DATABASE_URL is the widely-used convention for Postgres connection strings;
# honor it as a fallback so most hosting setups work unmodified.
POSTGRES_URL: Secret[str]
if _env_url := environ.get("DATABASE_URL"):
    POSTGRES_URL = _env_url

# Optional second URL for management operations (migrations, convergence,
# schema changes). When set, management commands connect via this URL
# instead of POSTGRES_URL. Common uses: bypassing a transaction-mode
# pgbouncer that can't handle DDL, or connecting as a DDL-capable role.
# Falls back to POSTGRES_URL when empty.
POSTGRES_MANAGEMENT_URL: Secret[str] = ""

# Connection pool options forwarded to psycopg_pool.ConnectionPool.
# Defaults match psycopg_pool's own defaults (max_size mirrors min_size when
# left alone).
POSTGRES_POOL_MIN_SIZE: int = 4
POSTGRES_POOL_MAX_SIZE: int = 20
POSTGRES_POOL_MAX_LIFETIME: float = 3600.0
POSTGRES_POOL_TIMEOUT: float = 30.0

# DDL timeouts. Applied per-statement via SET LOCAL before every framework-
# issued DDL in migrations and convergence. Values are Postgres interval
# strings ("3s", "500ms", "1min"). These do NOT affect application queries.
#
# lock_timeout: how long to wait for a lock before failing with
#   LockNotAvailable. Prevents the lock-queue cascade where a waiting
#   ACCESS EXCLUSIVE blocks every new query on the table.
#
# statement_timeout: how long a statement can run once it has its lock.
#   Only applied to statements that hold ACCESS EXCLUSIVE. Non-blocking
#   operations (CREATE INDEX CONCURRENTLY, VALIDATE CONSTRAINT) run
#   without a statement_timeout — the lock doesn't cascade, so letting
#   them run to completion on large tables is safe.
POSTGRES_MIGRATION_LOCK_TIMEOUT: str = "3s"
POSTGRES_MIGRATION_STATEMENT_TIMEOUT: str = "3s"
POSTGRES_CONVERGENCE_LOCK_TIMEOUT: str = "3s"
POSTGRES_CONVERGENCE_STATEMENT_TIMEOUT: str = "3s"

# Retry budget for the schema advisory lock that serializes schema-changing
# commands (see schema_lock.py). Non-blocking acquire, retried; the defaults
# wait up to an hour (720 × 5s) because a legitimate holder can be mid
# index build.
POSTGRES_SCHEMA_LOCK_RETRY_INTERVAL: float = 5.0
POSTGRES_SCHEMA_LOCK_MAX_RETRIES: int = 720

# How long schema commands (sync, migrations apply, converge) wait for the
# database to accept connections before giving up. Covers a database that's
# still starting (deploys, dev services, failovers) so those commands don't
# need a separate wait step in front of them. Configuration errors (bad
# credentials, bad URL) fail immediately regardless — retrying can't fix
# them. Set to 0 to fail on the first connection error.
POSTGRES_WAIT_TIMEOUT: float = 60.0
