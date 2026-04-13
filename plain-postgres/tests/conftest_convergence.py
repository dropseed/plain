"""Shared helpers for convergence tests."""

from __future__ import annotations

from plain.postgres import get_connection


def execute(sql: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(sql)


def constraint_exists(table: str, name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT 1 FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s
            """,
            [table, name],
        )
        return cursor.fetchone() is not None


def constraint_is_valid(table: str, name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT c.convalidated FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s
            """,
            [table, name],
        )
        row = cursor.fetchone()
        return row[0] if row else False


def constraint_is_deferrable(table: str, name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT c.condeferrable FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s
            """,
            [table, name],
        )
        row = cursor.fetchone()
        return row[0] if row else False


def create_invalid_index(name: str) -> None:
    """Create a normal index then mark it INVALID via pg_catalog."""
    execute(f'CREATE INDEX "{name}" ON "examples_car" ("make")')
    execute(
        f"""
        UPDATE pg_index SET indisvalid = false
        WHERE indexrelid = (SELECT oid FROM pg_class WHERE relname = '{name}')
        """
    )


def index_exists(name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s",
            [name],
        )
        return cursor.fetchone() is not None


def index_is_valid(name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT i.indisvalid
            FROM pg_index i
            JOIN pg_class c ON i.indexrelid = c.oid
            WHERE c.relname = %s
            """,
            [name],
        )
        row = cursor.fetchone()
        return row[0] if row else False


def get_fk_constraint_names(table: str) -> list[str]:
    """Return FK constraint names for a table."""
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.contype = 'f'
            ORDER BY c.conname
            """,
            [table],
        )
        return [row[0] for row in cursor.fetchall()]


def fk_on_delete_action(table: str, name: str) -> str | None:
    """Return pg_constraint.confdeltype char code for a FK constraint."""
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT c.confdeltype FROM pg_constraint c
            JOIN pg_class cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND c.conname = %s AND c.contype = 'f'
            """,
            [table, name],
        )
        row = cursor.fetchone()
        return row[0] if row else None


def column_is_not_null(table: str, column: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT a.attnotnull
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = %s AND a.attname = %s
            """,
            [table, column],
        )
        row = cursor.fetchone()
        return row[0] if row else False
