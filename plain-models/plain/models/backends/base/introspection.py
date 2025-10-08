from __future__ import annotations

from collections import namedtuple
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper

# Structure returned by DatabaseIntrospection.get_table_list()
TableInfo = namedtuple("TableInfo", ["name", "type"])

# Structure returned by the DB-API cursor.description interface (PEP 249)
FieldInfo = namedtuple(
    "FieldInfo",
    "name type_code display_size internal_size precision scale null_ok "
    "default collation",
)


class BaseDatabaseIntrospection:
    """Encapsulate backend-specific introspection utilities."""

    data_types_reverse: dict[Any, str] = {}

    def __init__(self, connection: BaseDatabaseWrapper) -> None:
        self.connection = connection

    def get_field_type(self, data_type: Any, description: Any) -> str:
        """
        Hook for a database backend to use the cursor description to
        match a Plain field type to a database column.

        For Oracle, the column data_type on its own is insufficient to
        distinguish between a FloatField and IntegerField, for example.
        """
        return self.data_types_reverse[data_type]

    def identifier_converter(self, name: str) -> str:
        """
        Apply a conversion to the identifier for the purposes of comparison.

        The default identifier converter is for case sensitive comparison.
        """
        return name

    def table_names(self, cursor: Any = None, include_views: bool = False) -> list[str]:
        """
        Return a list of names of all tables that exist in the database.
        Sort the returned table list by Python's default sorting. Do NOT use
        the database's ORDER BY here to avoid subtle differences in sorting
        order between databases.
        """

        def get_names(cursor: Any) -> list[str]:
            return sorted(
                ti.name
                for ti in self.get_table_list(cursor)
                if include_views or ti.type == "t"
            )

        if cursor is None:
            with self.connection.cursor() as cursor:
                return get_names(cursor)
        return get_names(cursor)

    def get_table_list(self, cursor: Any) -> list[TableInfo]:
        """
        Return an unsorted list of TableInfo named tuples of all tables and
        views that exist in the database.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseIntrospection may require a get_table_list() "
            "method"
        )

    def get_table_description(self, cursor: Any, table_name: str) -> list[FieldInfo]:
        """
        Return a description of the table with the DB-API cursor.description
        interface.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseIntrospection may require a "
            "get_table_description() method."
        )

    def get_migratable_models(self) -> Generator[Any, None, None]:
        from plain.models import models_registry
        from plain.packages import packages_registry

        return (
            model
            for package_config in packages_registry.get_package_configs()
            for model in models_registry.get_models(
                package_label=package_config.package_label
            )
            if model.model_options.can_migrate(self.connection)
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
            tables = [
                t for t in tables if self.identifier_converter(t) in existing_tables
            ]
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
        self, cursor: Any, table_name: str, table_fields: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """
        Return a list of introspected sequences for table_name. Each sequence
        is a dict: {'table': <table_name>, 'column': <column_name>}. An optional
        'name' key can be added if the backend supports named sequences.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseIntrospection may require a get_sequences() "
            "method"
        )

    def get_relations(self, cursor: Any, table_name: str) -> dict[str, tuple[str, str]]:
        """
        Return a dictionary of {field_name: (field_name_other_table, other_table)}
        representing all foreign keys in the given table.
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseIntrospection may require a "
            "get_relations() method."
        )

    def get_primary_key_column(self, cursor: Any, table_name: str) -> str | None:
        """
        Return the name of the primary key column for the given table.
        """
        columns = self.get_primary_key_columns(cursor, table_name)
        return columns[0] if columns else None

    def get_primary_key_columns(self, cursor: Any, table_name: str) -> list[str] | None:
        """Return a list of primary key columns for the given table."""
        for constraint in self.get_constraints(cursor, table_name).values():
            if constraint["primary_key"]:
                return constraint["columns"]
        return None

    def get_constraints(
        self, cursor: Any, table_name: str
    ) -> dict[str, dict[str, Any]]:
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index)
        across one or more columns.

        Return a dict mapping constraint names to their attributes,
        where attributes is a dict with keys:
         * columns: List of columns this covers
         * primary_key: True if primary key, False otherwise
         * unique: True if this is a unique constraint, False otherwise
         * foreign_key: (table, column) of target, or None
         * check: True if check constraint, False otherwise
         * index: True if index, False otherwise.
         * orders: The order (ASC/DESC) defined for the columns of indexes
         * type: The type of the index (btree, hash, etc.)

        Some backends may return special constraint names that don't exist
        if they don't name constraints of a certain type (e.g. SQLite)
        """
        raise NotImplementedError(
            "subclasses of BaseDatabaseIntrospection may require a get_constraints() "
            "method"
        )
