"""
Query subclasses which provide extra functionality beyond simple data retrieval.
"""

from __future__ import annotations

from typing import Any

from plain.models.exceptions import FieldError
from plain.models.sql.constants import CURSOR, GET_ITERATOR_CHUNK_SIZE, NO_RESULTS
from plain.models.sql.query import Query

__all__ = ["DeleteQuery", "UpdateQuery", "InsertQuery", "AggregateQuery"]


class DeleteQuery(Query):
    """A DELETE SQL query."""

    compiler = "SQLDeleteCompiler"

    def do_query(self, table: str, where: Any) -> int:
        self.alias_map = {table: self.alias_map[table]}
        self.where = where
        cursor = self.get_compiler().execute_sql(CURSOR)
        if cursor:
            with cursor:
                return cursor.rowcount
        return 0

    def delete_batch(self, id_list: list[Any]) -> int:
        """
        Set up and execute delete queries for all the objects in id_list.

        More than one physical query may be executed if there are a
        lot of values in id_list.
        """
        # number of objects deleted
        num_deleted = 0
        field = self.get_model_meta().get_field("id")
        for offset in range(0, len(id_list), GET_ITERATOR_CHUNK_SIZE):
            self.clear_where()
            self.add_filter(
                f"{field.attname}__in",
                id_list[offset : offset + GET_ITERATOR_CHUNK_SIZE],
            )
            num_deleted += self.do_query(self.model.model_options.db_table, self.where)
        return num_deleted


class UpdateQuery(Query):
    """An UPDATE SQL query."""

    compiler = "SQLUpdateCompiler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._setup_query()

    def _setup_query(self) -> None:
        """
        Run on initialization and at the end of chaining. Any attributes that
        would normally be set in __init__() should go here instead.
        """
        self.values: list[tuple[Any, Any, Any]] = []
        self.related_ids: dict[Any, list[Any]] | None = None
        self.related_updates: dict[Any, list[tuple[Any, Any, Any]]] = {}

    def clone(self) -> UpdateQuery:
        obj = super().clone()
        obj.related_updates = self.related_updates.copy()
        return obj  # type: ignore[return-value]

    def update_batch(self, id_list: list[Any], values: dict[str, Any]) -> None:
        self.add_update_values(values)
        for offset in range(0, len(id_list), GET_ITERATOR_CHUNK_SIZE):
            self.clear_where()
            self.add_filter(
                "id__in", id_list[offset : offset + GET_ITERATOR_CHUNK_SIZE]
            )
            self.get_compiler().execute_sql(NO_RESULTS)

    def add_update_values(self, values: dict[str, Any]) -> list[tuple[Any, Any, Any]]:
        """
        Convert a dictionary of field name to value mappings into an update
        query. This is the entry point for the public update() method on
        querysets.
        """
        values_seq = []
        for name, val in values.items():
            field = self.get_model_meta().get_field(name)
            direct = (
                not (field.auto_created and not field.concrete) or not field.concrete
            )
            model = field.model
            if not direct or (field.is_relation and field.many_to_many):
                raise FieldError(
                    f"Cannot update model field {field!r} (only non-relations and "
                    "foreign keys permitted)."
                )
            if model is not self.get_model_meta().model:
                self.add_related_update(model, field, val)
                continue
            values_seq.append((field, model, val))
        return self.add_update_fields(values_seq)

    def add_update_fields(self, values_seq: list[tuple[Any, Any, Any]]) -> None:
        """
        Append a sequence of (field, model, value) triples to the internal list
        that will be used to generate the UPDATE query. Might be more usefully
        called add_update_targets() to hint at the extra information here.
        """
        for field, model, val in values_seq:
            if hasattr(val, "resolve_expression"):
                # Resolve expressions here so that annotations are no longer needed
                val = val.resolve_expression(self, allow_joins=False, for_save=True)
            self.values.append((field, model, val))

    def add_related_update(self, model: Any, field: Any, value: Any) -> None:
        """
        Add (name, value) to an update query for an ancestor model.

        Update are coalesced so that only one update query per ancestor is run.
        """
        self.related_updates.setdefault(model, []).append((field, None, value))

    def get_related_updates(self) -> list[UpdateQuery]:
        """
        Return a list of query objects: one for each update required to an
        ancestor model. Each query will have the same filtering conditions as
        the current query but will only update a single table.
        """
        if not self.related_updates:
            return []
        result = []
        for model, values in self.related_updates.items():
            query = UpdateQuery(model)
            query.values = values
            if self.related_ids is not None:
                query.add_filter("id__in", self.related_ids[model])
            result.append(query)
        return result


class InsertQuery(Query):
    compiler = "SQLInsertCompiler"

    def __init__(
        self,
        *args: Any,
        on_conflict: str | None = None,
        update_fields: list[Any] | None = None,
        unique_fields: list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields: list[Any] = []
        self.objs: list[Any] = []
        self.on_conflict = on_conflict
        self.update_fields = update_fields or []
        self.unique_fields = unique_fields or []

    def insert_values(
        self, fields: list[Any], objs: list[Any], raw: bool = False
    ) -> None:
        self.fields = fields
        self.objs = objs
        self.raw = raw  # type: ignore[attr-defined]


class AggregateQuery(Query):
    """
    Take another query as a parameter to the FROM clause and only select the
    elements in the provided list.
    """

    compiler = "SQLAggregateCompiler"

    def __init__(self, model: Any, inner_query: Any) -> None:
        self.inner_query = inner_query
        super().__init__(model)
