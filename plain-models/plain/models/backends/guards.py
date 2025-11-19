"""Type guards for database backend narrowing.

These type guards allow type checkers to narrow BaseDatabaseWrapper types to
vendor-specific implementations based on runtime checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeIs

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.backends.mysql.base import MySQLDatabaseWrapper
    from plain.models.backends.postgresql.base import PostgreSQLDatabaseWrapper
    from plain.models.backends.sqlite3.base import SQLiteDatabaseWrapper


def is_sqlite_connection(
    connection: BaseDatabaseWrapper,
) -> TypeIs[SQLiteDatabaseWrapper]:
    """Type guard to narrow BaseDatabaseWrapper to SQLiteDatabaseWrapper.

    Args:
        connection: A database connection instance.

    Returns:
        True if the connection is a SQLite connection.

    Example:
        >>> if is_sqlite_connection(connection):
        >>>     # connection is now SQLiteDatabaseWrapper
        >>>     connection.ops.jsonfield_datatype_values
    """
    return connection.vendor == "sqlite"


def is_mysql_connection(
    connection: BaseDatabaseWrapper,
) -> TypeIs[MySQLDatabaseWrapper]:
    """Type guard to narrow BaseDatabaseWrapper to MySQLDatabaseWrapper.

    Args:
        connection: A database connection instance.

    Returns:
        True if the connection is a MySQL/MariaDB connection.
    """
    return connection.vendor == "mysql"


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
