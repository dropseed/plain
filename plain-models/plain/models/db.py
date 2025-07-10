from plain import signals

from .connections import DatabaseConnection
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


db_connection = DatabaseConnection()


# Register an event to reset saved queries when a Plain request is started.
def reset_queries(**kwargs):
    if db_connection.has_connection():
        db_connection.queries_log.clear()


signals.request_started.connect(reset_queries)


# Register an event to reset transaction state and close connections past
# their lifetime.
def close_old_connections(**kwargs):
    if db_connection.has_connection():
        db_connection.close_if_unusable_or_obsolete()


signals.request_started.connect(close_old_connections)
signals.request_finished.connect(close_old_connections)


__all__ = [
    "db_connection",
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
