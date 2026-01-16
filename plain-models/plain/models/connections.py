from __future__ import annotations

from threading import local
from typing import TYPE_CHECKING, Any, TypedDict

from plain.runtime import settings as plain_settings

if TYPE_CHECKING:
    from plain.models.backends.base.base import DatabaseWrapper


class DatabaseConfig(TypedDict, total=False):
    AUTOCOMMIT: bool
    CONN_MAX_AGE: int | None
    CONN_HEALTH_CHECKS: bool
    DISABLE_SERVER_SIDE_CURSORS: bool
    HOST: str
    NAME: str | None
    OPTIONS: dict[str, Any]
    PASSWORD: str
    PORT: str | int
    TEST: dict[str, Any]
    TIME_ZONE: str | None
    USER: str


class DatabaseConnection:
    """Lazy access to the single configured database connection."""

    __slots__ = ("_settings", "_local")

    def __init__(self) -> None:
        self._settings: DatabaseConfig = {}
        self._local = local()

    def configure_settings(self) -> DatabaseConfig:
        database = plain_settings.DATABASE

        database.setdefault("AUTOCOMMIT", True)
        database.setdefault("CONN_MAX_AGE", 0)
        database.setdefault("CONN_HEALTH_CHECKS", False)
        database.setdefault("OPTIONS", {})
        database.setdefault("TIME_ZONE", None)
        for setting in ["NAME", "USER", "PASSWORD", "HOST", "PORT"]:
            database.setdefault(setting, "")

        test_settings = database.setdefault("TEST", {})
        default_test_settings = [
            ("CHARSET", None),
            ("NAME", None),
        ]
        for key, value in default_test_settings:
            test_settings.setdefault(key, value)

        return database

    def create_connection(self) -> DatabaseWrapper:
        from plain.models.backends.base.base import DatabaseWrapper

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
        else:
            if not self.has_connection():
                self._local.conn = self.create_connection()

            setattr(self._local.conn, name, value)
