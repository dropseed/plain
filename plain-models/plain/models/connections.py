from functools import cached_property
from importlib import import_module
from threading import local
from typing import Any, TypedDict

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings as plain_settings
from plain.utils.module_loading import import_string

from .exceptions import ConnectionDoesNotExist

DEFAULT_DB_ALIAS = "default"


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


class ConnectionHandler:
    """
    Handler for database connections. Provides lazy connection creation
    and convenience methods for managing multiple database connections.
    """

    def __init__(self):
        self._settings: dict[str, DatabaseConfig] = {}
        self._connections = local()

    @cached_property
    def settings(self) -> DatabaseConfig:
        self._settings = self.configure_settings()
        return self._settings

    def configure_settings(self) -> DatabaseConfig:
        databases = plain_settings.DATABASES

        if DEFAULT_DB_ALIAS not in databases:
            raise ImproperlyConfigured(
                f"You must define a '{DEFAULT_DB_ALIAS}' database."
            )

        # Configure default settings.
        for conn in databases.values():
            conn.setdefault("AUTOCOMMIT", True)
            conn.setdefault("CONN_MAX_AGE", 0)
            conn.setdefault("CONN_HEALTH_CHECKS", False)
            conn.setdefault("OPTIONS", {})
            conn.setdefault("TIME_ZONE", None)
            for setting in ["NAME", "USER", "PASSWORD", "HOST", "PORT"]:
                conn.setdefault(setting, "")

            test_settings = conn.setdefault("TEST", {})
            default_test_settings = [
                ("CHARSET", None),
                ("COLLATION", None),
                ("MIRROR", None),
                ("NAME", None),
            ]
            for key, value in default_test_settings:
                test_settings.setdefault(key, value)

        return databases

    def create_connection(self, alias):
        database_config = self.settings[alias]
        backend = import_module(f"{database_config['ENGINE']}.base")
        return backend.DatabaseWrapper(database_config, alias)

    def __getitem__(self, alias):
        try:
            return getattr(self._connections, alias)
        except AttributeError:
            if alias not in self.settings:
                raise ConnectionDoesNotExist(f"The connection '{alias}' doesn't exist.")
        conn = self.create_connection(alias)
        setattr(self._connections, alias, conn)
        return conn

    def __setitem__(self, key, value):
        setattr(self._connections, key, value)

    def __delitem__(self, key):
        delattr(self._connections, key)

    def __iter__(self):
        return iter(self.settings)

    def all(self, initialized_only=False):
        return [
            self[alias]
            for alias in self
            # If initialized_only is True, return only initialized connections.
            if not initialized_only or hasattr(self._connections, alias)
        ]

    def close_all(self):
        for conn in self.all(initialized_only=True):
            conn.close()


class ConnectionRouter:
    def __init__(self, routers=None):
        """
        If routers is not specified, default to settings.DATABASE_ROUTERS.
        """
        self._routers = routers

    @cached_property
    def routers(self):
        if self._routers is None:
            self._routers = plain_settings.DATABASE_ROUTERS
        routers = []
        for r in self._routers:
            if isinstance(r, str):
                router = import_string(r)()
            else:
                router = r
            routers.append(router)
        return routers

    def _router_func(action):
        def _route_db(self, model, **hints):
            chosen_db = None
            for router in self.routers:
                try:
                    method = getattr(router, action)
                except AttributeError:
                    # If the router doesn't have a method, skip to the next one.
                    pass
                else:
                    chosen_db = method(model, **hints)
                    if chosen_db:
                        return chosen_db
            instance = hints.get("instance")
            if instance is not None and instance._state.db:
                return instance._state.db
            return DEFAULT_DB_ALIAS

        return _route_db

    db_for_read = _router_func("db_for_read")
    db_for_write = _router_func("db_for_write")

    def allow_relation(self, obj1, obj2, **hints):
        for router in self.routers:
            try:
                method = router.allow_relation
            except AttributeError:
                # If the router doesn't have a method, skip to the next one.
                pass
            else:
                allow = method(obj1, obj2, **hints)
                if allow is not None:
                    return allow
        return obj1._state.db == obj2._state.db

    def allow_migrate(self, db, package_label, **hints):
        for router in self.routers:
            try:
                method = router.allow_migrate
            except AttributeError:
                # If the router doesn't have a method, skip to the next one.
                continue

            allow = method(db, package_label, **hints)

            if allow is not None:
                return allow
        return True

    def allow_migrate_model(self, db, model):
        return self.allow_migrate(
            db,
            model._meta.package_label,
            model_name=model._meta.model_name,
            model=model,
        )

    def get_migratable_models(self, models_registry, package_label, db):
        """Return app models allowed to be migrated on provided db."""
        models = models_registry.get_models(package_label=package_label)
        return [model for model in models if self.allow_migrate_model(db, model)]
