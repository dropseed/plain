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

# Connection behavior
POSTGRES_CONN_MAX_AGE: int = 600
POSTGRES_CONN_HEALTH_CHECKS: bool = True
POSTGRES_TIME_ZONE: str | None = None

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
