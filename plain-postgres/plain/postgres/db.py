from __future__ import annotations

from typing import Any

from plain import signals

from .connections import get_connection, has_connection, use_management_connection

PLAIN_VERSION_PICKLE_KEY = "_plain_version"


# Register an event to reset saved queries when a Plain request is started.
def reset_queries(**kwargs: Any) -> None:
    if has_connection():
        get_connection().queries_log.clear()


signals.request_started.connect(reset_queries)


# Register an event to reset transaction state and close connections past
# their lifetime.
def close_old_connections(**kwargs: Any) -> None:
    if has_connection():
        get_connection().close_if_unusable_or_obsolete()


signals.request_started.connect(close_old_connections)
signals.request_finished.connect(close_old_connections)


__all__ = [
    "get_connection",
    "has_connection",
    "use_management_connection",
    "PLAIN_VERSION_PICKLE_KEY",
    "close_old_connections",
]
