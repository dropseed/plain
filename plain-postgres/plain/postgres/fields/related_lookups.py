from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.lookups import (
    Exact,
    GreaterThan,
    GreaterThanOrEqual,
    In,
    IsNull,
    LessThan,
    LessThanOrEqual,
    Lookup,
)

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.sql.compiler import SQLCompiler


def get_normalized_value(value: Any, lhs: Any) -> tuple[Any, ...]:
    from plain.postgres import Model
    from plain.postgres.fields.related import RelatedField

    if isinstance(value, Model):
        if value.id is None:
            raise ValueError("Model instances passed to related filters must be saved.")
        # FK relations are always single-column (target is remote `id`), so
        # path_infos[-1].target_fields is a 1-tuple.
        source = lhs.output_field.path_infos[-1].target_fields[0]
        while not isinstance(value, source.model) and isinstance(source, RelatedField):
            source = source.remote_field.model._model_meta.get_field(
                source.remote_field.field_name
            )
        return (getattr(value, source.attname),)
    if not isinstance(value, tuple):
        return (value,)
    return value


class RelatedIn(In):
    def get_prep_lookup(self) -> list[Any]:
        if self.rhs_is_direct_value():
            self.rhs = [get_normalized_value(val, self.lhs)[0] for val in self.rhs]
            # We need to run the related field's get_prep_value(). Consider
            # case ForeignKeyField to IntegerField given value 'abc'. The
            # ForeignKeyField itself doesn't have validation for non-integers,
            # so we must run validation using the target field.
            if hasattr(self.lhs.output_field, "path_infos"):
                target_field = self.lhs.output_field.path_infos[-1].target_fields[-1]
                self.rhs = [target_field.get_prep_value(v) for v in self.rhs]
        return super().get_prep_lookup()


class RelatedLookupMixin(Lookup):
    # Type hints for attributes/methods expected from Lookup base class
    lhs: Any
    rhs: Any
    prepare_rhs: bool
    lookup_name: str | None

    def get_prep_lookup(self) -> Any:
        if not hasattr(self.rhs, "resolve_expression"):
            self.rhs = get_normalized_value(self.rhs, self.lhs)[0]
            # We need to run the related field's get_prep_value(). Consider case
            # ForeignKeyField to IntegerField given value 'abc'. The ForeignKeyField itself
            # doesn't have validation for non-integers, so we must run validation
            # using the target field.
            if self.prepare_rhs and hasattr(self.lhs.output_field, "path_infos"):
                target_field = self.lhs.output_field.path_infos[-1].target_fields[-1]
                self.rhs = target_field.get_prep_value(self.rhs)

        return super().get_prep_lookup()

    def as_sql(
        self, compiler: SQLCompiler, connection: DatabaseConnection
    ) -> tuple[str, list[Any]]:
        sql, params = super().as_sql(compiler, connection)
        return sql, list(params)


class RelatedExact(RelatedLookupMixin, Exact):
    pass


class RelatedLessThan(RelatedLookupMixin, LessThan):
    pass


class RelatedGreaterThan(RelatedLookupMixin, GreaterThan):
    pass


class RelatedGreaterThanOrEqual(RelatedLookupMixin, GreaterThanOrEqual):
    pass


class RelatedLessThanOrEqual(RelatedLookupMixin, LessThanOrEqual):
    pass


class RelatedIsNull(RelatedLookupMixin, IsNull):
    pass
