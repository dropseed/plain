"""Type guards for database backend narrowing.

These type guards allow type checkers to narrow BaseDatabaseWrapper types to
vendor-specific implementations based on runtime checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeIs

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.backends.postgresql.base import PostgreSQLDatabaseWrapper


def is_postgresql_connection(
    connection: BaseDatabaseWrapper,
) -> TypeIs[PostgreSQLDatabaseWrapper]:
    """Type guard to narrow BaseDatabaseWrapper to PostgreSQLDatabaseWrapper.

    Args:
        connection: A database connection instance.

    Returns:
        True if the connection is a PostgreSQL connection.
    """
    return connection.vendor == "postgresql"
