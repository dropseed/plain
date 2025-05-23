import pkgutil
from functools import cached_property
from importlib import import_module

from plain import signals
from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings
from plain.utils.connection import BaseConnectionHandler, ConnectionProxy
from plain.utils.module_loading import import_string

DEFAULT_DB_ALIAS = "default"
PLAIN_VERSION_PICKLE_KEY = "_plain_version"


class Error(Exception):
    pass


class InterfaceError(Error):
    pass


class DatabaseError(Error):
    pass


class DataError(DatabaseError):
    pass


class OperationalError(DatabaseError):
    pass


class IntegrityError(DatabaseError):
    pass


class InternalError(DatabaseError):
    pass


class ProgrammingError(DatabaseError):
    pass


class NotSupportedError(DatabaseError):
    pass


class DatabaseErrorWrapper:
    """
    Context manager and decorator that reraises backend-specific database
    exceptions using Plain's common wrappers.
    """

    def __init__(self, wrapper):
        """
        wrapper is a database wrapper.

        It must have a Database attribute defining PEP-249 exceptions.
        """
        self.wrapper = wrapper

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            return
        for plain_exc_type in (
            DataError,
            OperationalError,
            IntegrityError,
            InternalError,
            ProgrammingError,
            NotSupportedError,
            DatabaseError,
            InterfaceError,
            Error,
        ):
            db_exc_type = getattr(self.wrapper.Database, plain_exc_type.__name__)
            if issubclass(exc_type, db_exc_type):
                plain_exc_value = plain_exc_type(*exc_value.args)
                # Only set the 'errors_occurred' flag for errors that may make
                # the connection unusable.
                if plain_exc_type not in (DataError, IntegrityError):
                    self.wrapper.errors_occurred = True
                raise plain_exc_value.with_traceback(traceback) from exc_value

    def __call__(self, func):
        # Note that we are intentionally not using @wraps here for performance
        # reasons. Refs #21109.
        def inner(*args, **kwargs):
            with self:
                return func(*args, **kwargs)

        return inner


def load_backend(backend_name):
    """
    Return a database backend's "base" module given a fully qualified database
    backend name, or raise an error if it doesn't exist.
    """
    try:
        return import_module(f"{backend_name}.base")
    except ImportError as e_user:
        # The database backend wasn't found. Display a helpful error message
        # listing all built-in database backends.
        import plain.models.backends

        builtin_backends = [
            name
            for _, name, ispkg in pkgutil.iter_modules(plain.models.backends.__path__)
            if ispkg and name not in {"base", "dummy"}
        ]
        if backend_name not in [f"plain.models.backends.{b}" for b in builtin_backends]:
            backend_reprs = map(repr, sorted(builtin_backends))
            raise ImproperlyConfigured(
                "{!r} isn't an available database backend or couldn't be "
                "imported. Check the above exception. To use one of the "
                "built-in backends, use 'plain.models.backends.XXX', where XXX "
                "is one of:\n"
                "    {}".format(backend_name, ", ".join(backend_reprs))
            ) from e_user
        else:
            # If there's some other error, this must be an error in Plain
            raise


class ConnectionHandler(BaseConnectionHandler):
    settings_name = "DATABASES"

    def configure_settings(self, databases):
        databases = super().configure_settings(databases)
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

    @property
    def databases(self):
        # Maintained for backward compatibility as some 3rd party packages have
        # made use of this private API in the past. It is no longer used within
        # Plain itself.
        return self.settings

    def create_connection(self, alias):
        db = self.settings[alias]
        backend = load_backend(db["ENGINE"])
        return backend.DatabaseWrapper(db, alias)


class ConnectionRouter:
    def __init__(self, routers=None):
        """
        If routers is not specified, default to settings.DATABASE_ROUTERS.
        """
        self._routers = routers

    @cached_property
    def routers(self):
        if self._routers is None:
            self._routers = settings.DATABASE_ROUTERS
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


connections = ConnectionHandler()

router = ConnectionRouter()

# For backwards compatibility. Prefer connections['default'] instead.
connection = ConnectionProxy(connections, DEFAULT_DB_ALIAS)


# Register an event to reset saved queries when a Plain request is started.
def reset_queries(**kwargs):
    for conn in connections.all(initialized_only=True):
        conn.queries_log.clear()


signals.request_started.connect(reset_queries)


# Register an event to reset transaction state and close connections past
# their lifetime.
def close_old_connections(**kwargs):
    for conn in connections.all(initialized_only=True):
        conn.close_if_unusable_or_obsolete()


signals.request_started.connect(close_old_connections)
signals.request_finished.connect(close_old_connections)
