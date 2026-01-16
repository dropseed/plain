from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

from plain.models.backends.utils import CursorWrapper
from plain.models.indexes import Index

if TYPE_CHECKING:
    from plain.models.backends.wrapper import DatabaseWrapper


class TableInfo(NamedTuple):
    """Structure returned by DatabaseIntrospection.get_table_list()."""

    name: str
    type: str
    comment: str | None


class FieldInfo(NamedTuple):
    """Structure returned by the DB-API cursor.description interface (PEP 249)."""

    name: str
    type_code: Any
    display_size: int | None
    internal_size: int | None
    precision: int | None
    scale: int | None
    null_ok: bool | None
    default: Any
    collation: str | None
    is_autofield: bool
    comment: str | None


class DatabaseIntrospection:
    """
    PostgreSQL-specific database introspection utilities.
    """

    # Maps PostgreSQL type codes to Plain Field types.
    data_types_reverse: dict[Any, str] = {
        16: "BooleanField",
        17: "BinaryField",
        20: "BigIntegerField",
        21: "SmallIntegerField",
        23: "IntegerField",
        25: "TextField",
        700: "FloatField",
        701: "FloatField",
        869: "GenericIPAddressField",
        1042: "CharField",  # blank-padded
        1043: "CharField",
        1082: "DateField",
        1083: "TimeField",
        1114: "DateTimeField",
        1184: "DateTimeField",
        1186: "DurationField",
        1266: "TimeField",
        1700: "DecimalField",
        2950: "UUIDField",
        3802: "JSONField",
    }
    index_default_access_method = "btree"

    ignored_tables: list[str] = []

    def __init__(self, connection: DatabaseWrapper) -> None:
        self.connection = connection

    def get_field_type(self, data_type: Any, description: Any) -> str:
        """
        Hook for a database backend to use the cursor description to
        match a Plain field type to a database column.
        """
        field_type = self.data_types_reverse[data_type]
        if description.is_autofield or (
            # Required for pre-Plain 4.1 serial columns.
            description.default and "nextval" in description.default
        ):
            if field_type == "BigIntegerField":
                return "PrimaryKeyField"
        return field_type

    def table_names(
        self, cursor: CursorWrapper | None = None, include_views: bool = False
    ) -> list[str]:
        """
        Return a list of names of all tables that exist in the database.
        Sort the returned table list by Python's default sorting. Do NOT use
        the database's ORDER BY here to avoid subtle differences in sorting
        order between databases.
        """

        def get_names(cursor: CursorWrapper) -> list[str]:
            return sorted(
                ti.name
                for ti in self.get_table_list(cursor)
                if include_views or ti.type == "t"
            )

        if cursor is None:
            with self.connection.cursor() as cursor:
                return get_names(cursor)
        return get_names(cursor)

    def get_table_list(self, cursor: CursorWrapper) -> Sequence[TableInfo]:
        """
        Return an unsorted list of TableInfo named tuples of all tables and
        views that exist in the database.
        """
        cursor.execute(
            """
            SELECT
                c.relname,
                CASE
                    WHEN c.relispartition THEN 'p'
                    WHEN c.relkind IN ('m', 'v') THEN 'v'
                    ELSE 't'
                END,
                obj_description(c.oid, 'pg_class')
            FROM pg_catalog.pg_class c
            LEFT JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('f', 'm', 'p', 'r', 'v')
                AND n.nspname NOT IN ('pg_catalog', 'pg_toast')
                AND pg_catalog.pg_table_is_visible(c.oid)
        """
        )
        return [
            TableInfo(*row)
            for row in cursor.fetchall()
            if row[0] not in self.ignored_tables
        ]

    def get_table_description(
        self, cursor: CursorWrapper, table_name: str
    ) -> Sequence[FieldInfo]:
        """
        Return a description of the table with the DB-API cursor.description
        interface.
        """
        # Query the pg_catalog tables as cursor.description does not reliably
        # return the nullable property and information_schema.columns does not
        # contain details of materialized views.
        cursor.execute(
            """
            SELECT
                a.attname AS column_name,
                NOT (a.attnotnull OR (t.typtype = 'd' AND t.typnotnull)) AS is_nullable,
                pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
                CASE WHEN collname = 'default' THEN NULL ELSE collname END AS collation,
                a.attidentity != '' AS is_autofield,
                col_description(a.attrelid, a.attnum) AS column_comment
            FROM pg_attribute a
            LEFT JOIN pg_attrdef ad ON a.attrelid = ad.adrelid AND a.attnum = ad.adnum
            LEFT JOIN pg_collation co ON a.attcollation = co.oid
            JOIN pg_type t ON a.atttypid = t.oid
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE c.relkind IN ('f', 'm', 'p', 'r', 'v')
                AND c.relname = %s
                AND n.nspname NOT IN ('pg_catalog', 'pg_toast')
                AND pg_catalog.pg_table_is_visible(c.oid)
        """,
            [table_name],
        )
        field_map = {line[0]: line[1:] for line in cursor.fetchall()}
        cursor.execute(
            f"SELECT * FROM {self.connection.ops.quote_name(table_name)} LIMIT 1"
        )
        return [
            FieldInfo(
                line.name,
                line.type_code,
                line.internal_size if line.display_size is None else line.display_size,
                line.internal_size,
                line.precision,
                line.scale,
                *field_map[line.name],
            )
            for line in cursor.description
        ]

    def get_migratable_models(self) -> Generator[Any, None, None]:
        from plain.models import models_registry
        from plain.packages import packages_registry

        return (
            model
            for package_config in packages_registry.get_package_configs()
            for model in models_registry.get_models(
                package_label=package_config.package_label
            )
        )

    def plain_table_names(
        self, only_existing: bool = False, include_views: bool = True
    ) -> list[str]:
        """
        Return a list of all table names that have associated Plain models and
        are in INSTALLED_PACKAGES.

        If only_existing is True, include only the tables in the database.
        """
        tables = set()
        for model in self.get_migratable_models():
            tables.add(model.model_options.db_table)
            tables.update(
                f.m2m_db_table() for f in model._model_meta.local_many_to_many
            )
        tables = list(tables)
        if only_existing:
            existing_tables = set(self.table_names(include_views=include_views))
            tables = [t for t in tables if t in existing_tables]
        return tables

    def sequence_list(self) -> list[dict[str, Any]]:
        """
        Return a list of information about all DB sequences for all models in
        all packages.
        """
        sequence_list = []
        with self.connection.cursor() as cursor:
            for model in self.get_migratable_models():
                sequence_list.extend(
                    self.get_sequences(
                        cursor,
                        model.model_options.db_table,
                        model._model_meta.local_fields,
                    )
                )
        return sequence_list

    def get_sequences(
        self, cursor: CursorWrapper, table_name: str, table_fields: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """
        Return a list of introspected sequences for table_name. Each sequence
        is a dict: {'table': <table_name>, 'column': <column_name>, 'name': <sequence_name>}.
        """
        cursor.execute(
            """
            SELECT
                s.relname AS sequence_name,
                a.attname AS colname
            FROM
                pg_class s
                JOIN pg_depend d ON d.objid = s.oid
                    AND d.classid = 'pg_class'::regclass
                    AND d.refclassid = 'pg_class'::regclass
                JOIN pg_attribute a ON d.refobjid = a.attrelid
                    AND d.refobjsubid = a.attnum
                JOIN pg_class tbl ON tbl.oid = d.refobjid
                    AND tbl.relname = %s
                    AND pg_catalog.pg_table_is_visible(tbl.oid)
            WHERE
                s.relkind = 'S';
        """,
            [table_name],
        )
        return [
            {"name": row[0], "table": table_name, "column": row[1]}
            for row in cursor.fetchall()
        ]

    def get_relations(
        self, cursor: CursorWrapper, table_name: str
    ) -> dict[str, tuple[str, str]]:
        """
        Return a dictionary of {field_name: (field_name_other_table, other_table)}
        representing all foreign keys in the given table.
        """
        cursor.execute(
            """
            SELECT a1.attname, c2.relname, a2.attname
            FROM pg_constraint con
            LEFT JOIN pg_class c1 ON con.conrelid = c1.oid
            LEFT JOIN pg_class c2 ON con.confrelid = c2.oid
            LEFT JOIN
                pg_attribute a1 ON c1.oid = a1.attrelid AND a1.attnum = con.conkey[1]
            LEFT JOIN
                pg_attribute a2 ON c2.oid = a2.attrelid AND a2.attnum = con.confkey[1]
            WHERE
                c1.relname = %s AND
                con.contype = 'f' AND
                c1.relnamespace = c2.relnamespace AND
                pg_catalog.pg_table_is_visible(c1.oid)
        """,
            [table_name],
        )
        return {row[0]: (row[2], row[1]) for row in cursor.fetchall()}

    def get_primary_key_column(
        self, cursor: CursorWrapper, table_name: str
    ) -> str | None:
        """
        Return the name of the primary key column for the given table.
        """
        columns = self.get_primary_key_columns(cursor, table_name)
        return columns[0] if columns else None

    def get_primary_key_columns(
        self, cursor: CursorWrapper, table_name: str
    ) -> list[str] | None:
        """Return a list of primary key columns for the given table."""
        for constraint in self.get_constraints(cursor, table_name).values():
            if constraint["primary_key"]:
                return constraint["columns"]
        return None

    def get_constraints(
        self, cursor: CursorWrapper, table_name: str
    ) -> dict[str, dict[str, Any]]:
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index) across
        one or more columns. Also retrieve the definition of expression-based
        indexes.
        """
        constraints: dict[str, dict[str, Any]] = {}
        # Loop over the key table, collecting things as constraints. The column
        # array must return column names in the same order in which they were
        # created.
        cursor.execute(
            """
            SELECT
                c.conname,
                array(
                    SELECT attname
                    FROM unnest(c.conkey) WITH ORDINALITY cols(colid, arridx)
                    JOIN pg_attribute AS ca ON cols.colid = ca.attnum
                    WHERE ca.attrelid = c.conrelid
                    ORDER BY cols.arridx
                ),
                c.contype,
                (SELECT fkc.relname || '.' || fka.attname
                FROM pg_attribute AS fka
                JOIN pg_class AS fkc ON fka.attrelid = fkc.oid
                WHERE fka.attrelid = c.confrelid AND fka.attnum = c.confkey[1]),
                cl.reloptions
            FROM pg_constraint AS c
            JOIN pg_class AS cl ON c.conrelid = cl.oid
            WHERE cl.relname = %s AND pg_catalog.pg_table_is_visible(cl.oid)
        """,
            [table_name],
        )
        for constraint, columns, kind, used_cols, options in cursor.fetchall():
            constraints[constraint] = {
                "columns": columns,
                "primary_key": kind == "p",
                "unique": kind in ["p", "u"],
                "foreign_key": tuple(used_cols.split(".", 1)) if kind == "f" else None,
                "check": kind == "c",
                "index": False,
                "definition": None,
                "options": options,
            }
        # Now get indexes
        cursor.execute(
            """
            SELECT
                indexname,
                array_agg(attname ORDER BY arridx),
                indisunique,
                indisprimary,
                array_agg(ordering ORDER BY arridx),
                amname,
                exprdef,
                s2.attoptions
            FROM (
                SELECT
                    c2.relname as indexname, idx.*, attr.attname, am.amname,
                    CASE
                        WHEN idx.indexprs IS NOT NULL THEN
                            pg_get_indexdef(idx.indexrelid)
                    END AS exprdef,
                    CASE am.amname
                        WHEN %s THEN
                            CASE (option & 1)
                                WHEN 1 THEN 'DESC' ELSE 'ASC'
                            END
                    END as ordering,
                    c2.reloptions as attoptions
                FROM (
                    SELECT *
                    FROM
                        pg_index i,
                        unnest(i.indkey, i.indoption)
                            WITH ORDINALITY koi(key, option, arridx)
                ) idx
                LEFT JOIN pg_class c ON idx.indrelid = c.oid
                LEFT JOIN pg_class c2 ON idx.indexrelid = c2.oid
                LEFT JOIN pg_am am ON c2.relam = am.oid
                LEFT JOIN
                    pg_attribute attr ON attr.attrelid = c.oid AND attr.attnum = idx.key
                WHERE c.relname = %s AND pg_catalog.pg_table_is_visible(c.oid)
            ) s2
            GROUP BY indexname, indisunique, indisprimary, amname, exprdef, attoptions;
        """,
            [self.index_default_access_method, table_name],
        )
        for (
            index,
            columns,
            unique,
            primary,
            orders,
            type_,
            definition,
            options,
        ) in cursor.fetchall():
            if index not in constraints:
                basic_index = (
                    type_ == self.index_default_access_method and options is None
                )
                constraints[index] = {
                    "columns": columns if columns != [None] else [],
                    "orders": orders if orders != [None] else [],
                    "primary_key": primary,
                    "unique": unique,
                    "foreign_key": None,
                    "check": False,
                    "index": True,
                    "type": Index.suffix if basic_index else type_,
                    "definition": definition,
                    "options": options,
                }
        return constraints
