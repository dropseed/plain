from __future__ import annotations

import decimal
from collections.abc import Callable, Sequence
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

from psycopg.types import numeric

from plain import exceptions, validators
from plain.preflight import PreflightResult

from .base import NOT_PROVIDED, DefaultableField

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection


class FloatField(DefaultableField[float]):
    db_type_sql = "double precision"
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be a float.',
    }
    description = "Floating point number"

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as e:
            raise e.__class__(
                f"Field '{self.name}' expected a number but got {value!r}.",
            ) from e

    def to_python(self, value: Any) -> float | None:
        if value is None:
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )


class IntegerField(DefaultableField[int]):
    db_type_sql = "integer"
    integer_range: tuple[int, int] = (-2147483648, 2147483647)
    psycopg_type: type = numeric.Int4
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be an integer.',
    }
    description = "Integer"

    @cached_property
    def validators(self) -> list[Callable[..., Any]]:
        # These validators can't be added at field initialization time since
        # they're based on values retrieved from the database connection.
        validators_ = super().validators
        min_value, max_value = self.integer_range
        if min_value is not None and not any(
            (
                isinstance(validator, validators.MinValueValidator)
                and (
                    validator.limit_value()
                    if callable(validator.limit_value)
                    else validator.limit_value
                )
                >= min_value
            )
            for validator in validators_
        ):
            validators_.append(validators.MinValueValidator(min_value))
        if max_value is not None and not any(
            (
                isinstance(validator, validators.MaxValueValidator)
                and (
                    validator.limit_value()
                    if callable(validator.limit_value)
                    else validator.limit_value
                )
                <= max_value
            )
            for validator in validators_
        ):
            validators_.append(validators.MaxValueValidator(max_value))
        return validators_

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise e.__class__(
                f"Field '{self.name}' expected a number but got {value!r}.",
            ) from e

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        from plain.postgres.expressions import ResolvableExpression

        value = super().get_db_prep_value(value, connection, prepared)
        if value is None or isinstance(value, ResolvableExpression):
            return value
        return self.psycopg_type(value)

    def to_python(self, value: Any) -> int | None:
        if value is None:
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )


class BigIntegerField(IntegerField):
    db_type_sql = "bigint"
    integer_range = (-9223372036854775808, 9223372036854775807)
    psycopg_type = numeric.Int8
    description = "Big (8 byte) integer"


class SmallIntegerField(IntegerField):
    db_type_sql = "smallint"
    integer_range = (-32768, 32767)
    psycopg_type = numeric.Int2
    description = "Small integer"


class DecimalField(DefaultableField[decimal.Decimal]):
    db_type_sql = "numeric(%(max_digits)s,%(decimal_places)s)"
    empty_strings_allowed = False
    default_error_messages = {
        "invalid": '"%(value)s" value must be a decimal number.',
    }
    description = "Decimal number"

    def __init__(
        self,
        *,
        max_digits: int | None = None,
        decimal_places: int | None = None,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
        error_messages: dict[str, str] | None = None,
    ):
        self.max_digits, self.decimal_places = max_digits, decimal_places
        super().__init__(
            required=required,
            allow_null=allow_null,
            default=default,
            validators=validators,
            error_messages=error_messages,
        )

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)

        digits_errors = [
            *self._check_decimal_places(),
            *self._check_max_digits(),
        ]
        if not digits_errors:
            errors.extend(self._check_decimal_places_and_max_digits())
        else:
            errors.extend(digits_errors)
        return errors

    def _check_decimal_places(self) -> list[PreflightResult]:
        if self.decimal_places is None:
            return [
                PreflightResult(
                    fix="DecimalFields must define a 'decimal_places' attribute.",
                    obj=self,
                    id="fields.decimalfield_missing_decimal_places",
                )
            ]
        try:
            decimal_places = int(self.decimal_places)
            if decimal_places < 0:
                raise ValueError()
        except ValueError:
            return [
                PreflightResult(
                    fix="'decimal_places' must be a non-negative integer.",
                    obj=self,
                    id="fields.decimalfield_invalid_decimal_places",
                )
            ]
        else:
            return []

    def _check_max_digits(self) -> list[PreflightResult]:
        if self.max_digits is None:
            return [
                PreflightResult(
                    fix="DecimalFields must define a 'max_digits' attribute.",
                    obj=self,
                    id="fields.decimalfield_missing_max_digits",
                )
            ]
        try:
            max_digits = int(self.max_digits)
            if max_digits <= 0:
                raise ValueError()
        except ValueError:
            return [
                PreflightResult(
                    fix="'max_digits' must be a positive integer.",
                    obj=self,
                    id="fields.decimalfield_invalid_max_digits",
                )
            ]
        else:
            return []

    def _check_decimal_places_and_max_digits(self) -> list[PreflightResult]:
        if self.decimal_places is None or self.max_digits is None:
            return []
        if self.decimal_places > self.max_digits:
            return [
                PreflightResult(
                    fix="'max_digits' must be greater or equal to 'decimal_places'.",
                    obj=self,
                    id="fields.decimalfield_decimal_places_exceeds_max_digits",
                )
            ]
        return []

    @cached_property
    def validators(self) -> list[Callable[..., Any]]:
        return super().validators + [
            validators.DecimalValidator(self.max_digits, self.decimal_places)
        ]

    @cached_property
    def context(self) -> decimal.Context:
        return decimal.Context(prec=self.max_digits)

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.max_digits is not None:
            kwargs["max_digits"] = self.max_digits
        if self.decimal_places is not None:
            kwargs["decimal_places"] = self.decimal_places
        return name, path, args, kwargs

    def to_python(self, value: Any) -> decimal.Decimal | None:
        if value is None:
            return value
        try:
            if isinstance(value, float):
                decimal_value = self.context.create_decimal_from_float(value)
            else:
                decimal_value = decimal.Decimal(value)
        except (decimal.InvalidOperation, TypeError, ValueError):
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )
        if not decimal_value.is_finite():
            raise exceptions.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )
        return decimal_value

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)


class PrimaryKeyField(BigIntegerField):
    db_type_suffix_sql = "GENERATED BY DEFAULT AS IDENTITY"
    cast_db_type_sql = "bigint"
    db_returning = True

    def __init__(self):
        super().__init__(required=False)
        self.primary_key = True
        self.auto_created = True

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        errors = super().preflight(**kwargs)
        # Remove the reserved_field_name_id error for 'id' field name since PrimaryKeyField is allowed to use it
        errors = [e for e in errors if e.id != "fields.reserved_field_name_id"]
        return errors

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        # PrimaryKeyField takes no parameters, so we return an empty kwargs dict
        return (
            self.name,
            "plain.postgres.PrimaryKeyField",
            cast(list[Any], []),
            cast(dict[str, Any], {}),
        )

    def validate(self, value: Any, model_instance: Model) -> None:
        pass

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def rel_db_type(self) -> str | None:
        return BigIntegerField().db_type()
