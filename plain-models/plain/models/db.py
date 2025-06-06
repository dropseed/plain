from plain import signals

from .connections import (
    DEFAULT_DB_ALIAS,
    ConnectionHandler,
    ConnectionRouter,
)
from .exceptions import (
    ConnectionDoesNotExist,
    DatabaseError,
    DatabaseErrorWrapper,
    DataError,
    Error,
    IntegrityError,
    InterfaceError,
    InternalError,
    NotSupportedError,
    OperationalError,
    ProgrammingError,
)

PLAIN_VERSION_PICKLE_KEY = "_plain_version"


connections = ConnectionHandler()

router = ConnectionRouter()


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


__all__ = [
    "connections",
    "router",
    "DEFAULT_DB_ALIAS",
    "PLAIN_VERSION_PICKLE_KEY",
    "Error",
    "InterfaceError",
    "DatabaseError",
    "DataError",
    "OperationalError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "NotSupportedError",
    "ConnectionDoesNotExist",
    "DatabaseErrorWrapper",
    "reset_queries",
    "close_old_connections",
]
