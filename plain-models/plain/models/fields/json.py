from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from plain import exceptions, preflight
from plain.models import expressions, lookups
from plain.models.constants import LOOKUP_SEP
from plain.models.fields import TextField
from plain.models.lookups import (
    FieldGetDbPrepValueMixin,
    Lookup,
    OperatorLookup,
    Transform,
)

from . import Field

if TYPE_CHECKING:
    from plain.models.backends.wrapper import DatabaseWrapper
    from plain.models.sql.compiler import SQLCompiler
    from plain.preflight.results import PreflightResult

__all__ = ["JSONField"]


class JSONField(Field):
    empty_strings_allowed = False
    description = "A JSON object"
    default_error_messages = {
        "invalid": "Value must be valid JSON.",
    }
    _default_fix = ("dict", "{}")

    def __init__(
        self,
        *,
        encoder: type[json.JSONEncoder] | None = None,
        decoder: type[json.JSONDecoder] | None = None,
        **kwargs: Any,
    ):
        if encoder and not callable(encoder):
            raise ValueError("The encoder parameter must be a callable object.")
        if decoder and not callable(decoder):
            raise ValueError("The decoder parameter must be a callable object.")
        self.encoder = encoder
        self.decoder = decoder
        super().__init__(**kwargs)

    def _check_default(self) -> list[PreflightResult]:
        if (
            self.has_default()
            and self.default is not None
            and not callable(self.default)
        ):
            return [
                preflight.PreflightResult(
                    fix=(
                        f"{self.__class__.__name__} default should be a callable instead of an instance "
                        "so that it's not shared between all field instances. "
                        "Use a callable instead, e.g., use `{}` instead of "
                        "`{}`.".format(*self._default_fix)
                    ),
                    obj=self,
                    id="fields.invalid_choice_mixin_default",
                    warning=True,
                )
            ]
        else:
            return []

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)
        errors.extend(self._check_default())
        errors.extend(self._check_supported())
        return errors

    def _check_supported(self) -> list[PreflightResult]:
        # PostgreSQL always supports JSONField (native JSONB type).
        return []

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.encoder is not None:
            kwargs["encoder"] = self.encoder
        if self.decoder is not None:
            kwargs["decoder"] = self.decoder
        return name, path, args, kwargs

    def from_db_value(
        self, value: Any, expression: Any, connection: DatabaseWrapper
    ) -> Any:
        if value is None:
            return value
        # KeyTransform may extract non-string values directly.
        if isinstance(expression, KeyTransform) and not isinstance(value, str):
            return value
        try:
            return json.loads(value, cls=self.decoder)
        except json.JSONDecodeError:
            return value

    def get_internal_type(self) -> str:
        return "JSONField"

    def get_db_prep_value(
        self, value: Any, connection: DatabaseWrapper, prepared: bool = False
    ) -> Any:
        if isinstance(value, expressions.Value) and isinstance(
            value.output_field, JSONField
        ):
            value = value.value
        elif hasattr(value, "as_sql"):
            return value
        return connection.ops.adapt_json_value(value, self.encoder)

    def get_db_prep_save(self, value: Any, connection: DatabaseWrapper) -> Any:
        if value is None:
            return value
        return self.get_db_prep_value(value, connection)

    def get_transform(
        self, lookup_name: str
    ) -> type[Transform] | Callable[..., Any] | None:
        # Always returns a transform (never None in practice)
        transform = super().get_transform(lookup_name)
        if transform:
            return transform
        return KeyTransformFactory(lookup_name)

    def validate(self, value: Any, model_instance: Any) -> None:
        super().validate(value, model_instance)
        try:
            json.dumps(value, cls=self.encoder)
        except TypeError:
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )

    def value_to_string(self, obj: Any) -> Any:
        return self.value_from_object(obj)


class DataContains(FieldGetDbPrepValueMixin, OperatorLookup):
    lookup_name = "contains"
    # PostgreSQL @> operator checks if left JSON contains right JSON.
    operator = "@>"


class ContainedBy(FieldGetDbPrepValueMixin, OperatorLookup):
    lookup_name = "contained_by"
    # PostgreSQL <@ operator checks if left JSON is contained by right JSON.
    operator = "<@"


class HasKeyLookup(OperatorLookup):
    """Lookup for checking if a JSON field has a key."""

    logical_operator: str | None = None

    def as_sql(
        self, compiler: SQLCompiler, connection: DatabaseWrapper
    ) -> tuple[str, tuple[Any, ...]]:
        # Handle KeyTransform on RHS by expanding it into LHS chain.
        if isinstance(self.rhs, KeyTransform):
            *_, rhs_key_transforms = self.rhs.preprocess_lhs(compiler, connection)
            for key in rhs_key_transforms[:-1]:
                self.lhs = KeyTransform(key, self.lhs)
            self.rhs = rhs_key_transforms[-1]
        return super().as_sql(compiler, connection)


class HasKey(HasKeyLookup):
    lookup_name = "has_key"
    # PostgreSQL ? operator checks if key exists.
    operator = "?"
    prepare_rhs = False


class HasKeys(HasKeyLookup):
    lookup_name = "has_keys"
    # PostgreSQL ?& operator checks if all keys exist.
    operator = "?&"
    logical_operator = " AND "

    def get_prep_lookup(self) -> list[str]:
        return [str(item) for item in self.rhs]


class HasAnyKeys(HasKeys):
    lookup_name = "has_any_keys"
    # PostgreSQL ?| operator checks if any key exists.
    operator = "?|"
    logical_operator = " OR "


class JSONExact(lookups.Exact):
    can_use_none_as_rhs = True

    def process_rhs(
        self, compiler: SQLCompiler, connection: DatabaseWrapper
    ) -> tuple[str, list[Any]] | tuple[list[str], list[Any]]:
        rhs, rhs_params = super().process_rhs(compiler, connection)
        if isinstance(rhs, str):
            # Treat None lookup values as null.
            if rhs == "%s" and rhs_params == [None]:
                rhs_params = ["null"]
            return rhs, rhs_params
        else:
            return rhs, rhs_params


class JSONIContains(lookups.IContains):
    pass


JSONField.register_lookup(DataContains)
JSONField.register_lookup(ContainedBy)
JSONField.register_lookup(HasKey)
JSONField.register_lookup(HasKeys)
JSONField.register_lookup(HasAnyKeys)
JSONField.register_lookup(JSONExact)
JSONField.register_lookup(JSONIContains)


class KeyTransform(Transform):
    # PostgreSQL -> operator extracts JSON object field as JSON.
    operator = "->"
    # PostgreSQL #> operator extracts nested JSON path as JSON.
    nested_operator = "#>"

    def __init__(self, key_name: str, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.key_name = str(key_name)

    def preprocess_lhs(
        self, compiler: SQLCompiler, connection: DatabaseWrapper
    ) -> tuple[str, tuple[Any, ...], list[str]]:
        key_transforms = [self.key_name]
        previous = self.lhs
        while isinstance(previous, KeyTransform):
            key_transforms.insert(0, previous.key_name)
            previous = previous.lhs
        lhs, params = compiler.compile(previous)
        return lhs, params, key_transforms

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: DatabaseWrapper,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        lhs, params, key_transforms = self.preprocess_lhs(compiler, connection)
        if len(key_transforms) > 1:
            sql = f"({lhs} {self.nested_operator} %s)"
            return sql, list(params) + [key_transforms]
        try:
            lookup = int(self.key_name)
        except ValueError:
            lookup = self.key_name
        return f"({lhs} {self.operator} %s)", list(params) + [lookup]


class KeyTextTransform(KeyTransform):
    # PostgreSQL ->> operator extracts JSON object field as text.
    operator = "->>"
    # PostgreSQL #>> operator extracts nested JSON path as text.
    nested_operator = "#>>"
    output_field = TextField()

    @classmethod
    def from_lookup(cls, lookup: str) -> Any:
        transform, *keys = lookup.split(LOOKUP_SEP)
        if not keys:
            raise ValueError("Lookup must contain key or index transforms.")
        for key in keys:
            transform = cls(key, transform)
        return transform


KT = KeyTextTransform.from_lookup


class KeyTransformTextLookupMixin(Lookup):
    """
    Mixin for lookups expecting text LHS from a JSONField key lookup.
    Uses the ->> operator to extract JSON values as text.
    """

    def __init__(self, key_transform: Any, *args: Any, **kwargs: Any):
        if not isinstance(key_transform, KeyTransform):
            raise TypeError(
                "Transform should be an instance of KeyTransform in order to "
                "use this lookup."
            )
        key_text_transform = KeyTextTransform(
            key_transform.key_name,
            *key_transform.source_expressions,
            **key_transform.extra,
        )
        super().__init__(key_text_transform, *args, **kwargs)


class KeyTransformIsNull(lookups.IsNull):
    # key__isnull=False is the same as has_key='key'
    pass


class KeyTransformIn(lookups.In):
    def resolve_expression_parameter(
        self,
        compiler: SQLCompiler,
        connection: DatabaseWrapper,
        sql: str,
        param: Any,
    ) -> tuple[str, list[Any]]:
        sql, params = super().resolve_expression_parameter(
            compiler,
            connection,
            sql,
            param,
        )
        return sql, list(params)


class KeyTransformExact(JSONExact):
    def process_rhs(
        self, compiler: SQLCompiler, connection: DatabaseWrapper
    ) -> tuple[str, list[Any]] | tuple[list[str], list[Any]]:
        if isinstance(self.rhs, KeyTransform):
            return super(lookups.Exact, self).process_rhs(compiler, connection)
        return super().process_rhs(compiler, connection)


class KeyTransformIExact(KeyTransformTextLookupMixin, lookups.IExact):
    pass


class KeyTransformIContains(KeyTransformTextLookupMixin, lookups.IContains):
    pass


class KeyTransformStartsWith(KeyTransformTextLookupMixin, lookups.StartsWith):
    pass


class KeyTransformIStartsWith(KeyTransformTextLookupMixin, lookups.IStartsWith):
    pass


class KeyTransformEndsWith(KeyTransformTextLookupMixin, lookups.EndsWith):
    pass


class KeyTransformIEndsWith(KeyTransformTextLookupMixin, lookups.IEndsWith):
    pass


class KeyTransformRegex(KeyTransformTextLookupMixin, lookups.Regex):
    pass


class KeyTransformIRegex(KeyTransformTextLookupMixin, lookups.IRegex):
    pass


class KeyTransformLt(lookups.LessThan):
    pass


class KeyTransformLte(lookups.LessThanOrEqual):
    pass


class KeyTransformGt(lookups.GreaterThan):
    pass


class KeyTransformGte(lookups.GreaterThanOrEqual):
    pass


KeyTransform.register_lookup(KeyTransformIn)
KeyTransform.register_lookup(KeyTransformExact)
KeyTransform.register_lookup(KeyTransformIExact)
KeyTransform.register_lookup(KeyTransformIsNull)
KeyTransform.register_lookup(KeyTransformIContains)
KeyTransform.register_lookup(KeyTransformStartsWith)
KeyTransform.register_lookup(KeyTransformIStartsWith)
KeyTransform.register_lookup(KeyTransformEndsWith)
KeyTransform.register_lookup(KeyTransformIEndsWith)
KeyTransform.register_lookup(KeyTransformRegex)
KeyTransform.register_lookup(KeyTransformIRegex)

KeyTransform.register_lookup(KeyTransformLt)
KeyTransform.register_lookup(KeyTransformLte)
KeyTransform.register_lookup(KeyTransformGt)
KeyTransform.register_lookup(KeyTransformGte)


class KeyTransformFactory:
    def __init__(self, key_name: str):
        self.key_name = key_name

    def __call__(self, *args: Any, **kwargs: Any) -> KeyTransform:
        return KeyTransform(self.key_name, *args, **kwargs)
