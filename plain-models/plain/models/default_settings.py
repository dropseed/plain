from os import environ

from . import database_url
from .connections import DatabaseConfig

# Make DATABASE a required setting
DATABASE: DatabaseConfig

# Automatically configure DATABASE if a DATABASE_URL was given in the environment
if "DATABASE_URL" in environ:
    DATABASE = database_url.parse_database_url(
        environ["DATABASE_URL"],
        # Enable persistent connections by default
        conn_max_age=int(environ.get("DATABASE_CONN_MAX_AGE", 600)),
        conn_health_checks=environ.get("DATABASE_CONN_HEALTH_CHECKS", "true").lower()
        in [
            "true",
            "1",
        ],
    )
