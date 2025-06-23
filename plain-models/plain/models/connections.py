from importlib import import_module
from threading import local
from typing import Any, TypedDict

from plain.runtime import settings as plain_settings


class DatabaseConfig(TypedDict, total=False):
    AUTOCOMMIT: bool
    CONN_MAX_AGE: int | None
    CONN_HEALTH_CHECKS: bool
    DISABLE_SERVER_SIDE_CURSORS: bool
    ENGINE: str
    HOST: str
    NAME: str
    OPTIONS: dict[str, Any] | None
    PASSWORD: str
    PORT: str | int
    TEST: dict[str, Any]
    TIME_ZONE: str
    USER: str


class DatabaseConnection:
    """Lazy access to the single configured database connection."""

    __slots__ = ("_settings", "_local")

    def __init__(self):
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
            ("COLLATION", None),
            ("MIRROR", None),
            ("NAME", None),
        ]
        for key, value in default_test_settings:
            test_settings.setdefault(key, value)

        return database

    def create_connection(self):
        database_config = self.configure_settings()
        backend = import_module(f"{database_config['ENGINE']}.base")
        return backend.DatabaseWrapper(database_config)

    def has_connection(self):
        return hasattr(self._local, "conn")

    def __getattr__(self, attr):
        if not self.has_connection():
            self._local.conn = self.create_connection()

        return getattr(self._local.conn, attr)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            if not self.has_connection():
                self._local.conn = self.create_connection()

            setattr(self._local.conn, name, value)
