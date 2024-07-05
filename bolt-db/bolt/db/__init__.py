from bolt import signals
from bolt.db.utils import (
    BOLT_VERSION_PICKLE_KEY,
    DEFAULT_DB_ALIAS,
    ConnectionHandler,
    ConnectionRouter,
    DatabaseError,
    DataError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
)
from bolt.utils.connection import ConnectionProxy

from . import preflight  # noqa

__all__ = [
    "connection",
    "connections",
    "router",
    "DatabaseError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "DataError",
    "NotSupportedError",
    "Error",
    "InterfaceError",
    "OperationalError",
    "DEFAULT_DB_ALIAS",
    "BOLT_VERSION_PICKLE_KEY",
]

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
