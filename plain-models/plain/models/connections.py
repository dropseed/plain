from __future__ import annotations

from threading import local
from typing import TYPE_CHECKING, Any, TypedDict

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.models.postgres.wrapper import DatabaseWrapper


class DatabaseConfig(TypedDict, total=False):
    CONN_MAX_AGE: int | None
    CONN_HEALTH_CHECKS: bool
    HOST: str
    DATABASE: str | None
    OPTIONS: dict[str, Any]
    PASSWORD: str
    PORT: int | None
    TEST: dict[str, Any]
    TIME_ZONE: str | None
    USER: str


class DatabaseConnection:
    """Lazy access to the single configured database connection."""

    __slots__ = ("_local",)

    def __init__(self) -> None:
        self._local = local()

    def configure_settings(self) -> DatabaseConfig:
        if plain_settings.POSTGRES_DATABASE == "":
            raise ImproperlyConfigured(
                "The PostgreSQL database has been disabled (DATABASE_URL=none). "
                "No database operations are available in this context."
            )
        if not plain_settings.POSTGRES_DATABASE:  # None or unresolved setting
            raise ImproperlyConfigured(
                "PostgreSQL database is not configured. "
                "Set DATABASE_URL or the individual POSTGRES_* settings."
            )

        return {
            "DATABASE": plain_settings.POSTGRES_DATABASE,
            "USER": plain_settings.POSTGRES_USER,
            "PASSWORD": plain_settings.POSTGRES_PASSWORD,
            "HOST": plain_settings.POSTGRES_HOST,
            "PORT": plain_settings.POSTGRES_PORT,
            "CONN_MAX_AGE": plain_settings.POSTGRES_CONN_MAX_AGE,
            "CONN_HEALTH_CHECKS": plain_settings.POSTGRES_CONN_HEALTH_CHECKS,
            "OPTIONS": plain_settings.POSTGRES_OPTIONS,
            "TIME_ZONE": plain_settings.POSTGRES_TIME_ZONE,
            "TEST": {"DATABASE": None},
        }

    def create_connection(self) -> DatabaseWrapper:
        from plain.models.postgres.wrapper import DatabaseWrapper

        database_config = self.configure_settings()
        return DatabaseWrapper(database_config)

    def has_connection(self) -> bool:
        return hasattr(self._local, "conn")

    def __getattr__(self, attr: str) -> Any:
        if not self.has_connection():
            self._local.conn = self.create_connection()

        return getattr(self._local.conn, attr)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
            return

        if not self.has_connection():
            self._local.conn = self.create_connection()

        setattr(self._local.conn, name, value)
