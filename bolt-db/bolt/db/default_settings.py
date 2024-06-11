from os import environ

from . import database_url

# Make DATABASES a required setting
DATABASES: dict

# Automatically configure DATABASES if a DATABASE_URL was given in the environment
if "DATABASE_URL" in environ:
    DATABASES = {
        "default": database_url.parse(
            environ["DATABASE_URL"],
            # Enable persistent connections by default
            conn_max_age=int(environ.get("DATABASE_CONN_MAX_AGE", 600)),
            conn_health_checks=environ.get(
                "DATABASE_CONN_HEALTH_CHECKS", "true"
            ).lower()
            in [
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
