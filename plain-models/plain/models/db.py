from __future__ import annotations

from typing import Any

from plain import signals

from .connections import get_connection, has_connection, return_connection
from .exceptions import (
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


# Register an event to reset saved queries when a Plain request is started.
def reset_queries(**kwargs: Any) -> None:
    if has_connection():
        get_connection().queries_log.clear()


signals.request_started.connect(reset_queries)


# Return the connection to the pool when a request finishes.
def return_connection_to_pool(**kwargs: Any) -> None:
    return_connection()


signals.request_finished.connect(return_connection_to_pool)


__all__ = [
    "get_connection",
    "has_connection",
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
    "DatabaseErrorWrapper",
    "return_connection_to_pool",
]
