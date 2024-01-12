from os import environ

from . import database_url

# Database connection info. If left empty, will default to the dummy backend.
DATABASES = {
    "default": database_url.parse(
        environ["DATABASE_URL"],
        # Enable persistent connections by default
        conn_max_age=int(environ.get("DATABASE_CONN_MAX_AGE", 600)),
        conn_health_checks=environ.get("DATABASE_CONN_HEALTH_CHECKS", "true").lower() in [
            "true",
            "1",
        ],
    )
}

# Classes used to implement DB routing behavior.
DATABASE_ROUTERS = []

# The tablespaces to use for each model when not specified otherwise.
DEFAULT_TABLESPACE = ""
DEFAULT_INDEX_TABLESPACE = ""

# Default primary key field type.
DEFAULT_AUTO_FIELD = "bolt.db.models.AutoField"
