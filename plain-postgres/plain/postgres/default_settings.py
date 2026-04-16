from os import environ

from plain.runtime.secret import Secret

from . import database_url

# Connection behavior (always have defaults)
POSTGRES_PORT: int | None = None
POSTGRES_CONN_MAX_AGE: int = 600
POSTGRES_CONN_HEALTH_CHECKS: bool = True
POSTGRES_OPTIONS: dict = {}
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

if "DATABASE_URL" in environ:
    _db_url = environ["DATABASE_URL"]
    if _db_url.lower() == "none":
        # Explicitly disable database (e.g. during Docker builds)
        POSTGRES_HOST: str = ""
        POSTGRES_DATABASE: str = ""
        POSTGRES_USER: str = ""
        POSTGRES_PASSWORD: Secret[str] = ""
    else:
        _parsed = database_url.parse_database_url(_db_url)
        POSTGRES_HOST: str = _parsed["HOST"]
        POSTGRES_DATABASE: str = _parsed["DATABASE"] or ""
        POSTGRES_USER: str = _parsed["USER"]
        POSTGRES_PASSWORD: Secret[str] = _parsed["PASSWORD"]
        if _parsed["PORT"]:
            POSTGRES_PORT = _parsed["PORT"]
        if _parsed.get("OPTIONS"):
            POSTGRES_OPTIONS = _parsed["OPTIONS"]
else:
    # Individual settings are required when no DATABASE_URL is provided.
    # Set via PLAIN_POSTGRES_* environment variables or in app/settings.py.
    POSTGRES_HOST: str
    POSTGRES_DATABASE: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: Secret[str]
