from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from plain import validators
from plain.preflight import PreflightResult
from plain.validators import MaxLengthValidator

from .base import NOT_PROVIDED, ChoicesField, ColumnField

if TYPE_CHECKING:
    from plain.postgres.functions.random import RandomString


class TextField(ChoicesField[str]):
    db_type_sql = "text"

    def __init__(
        self,
        *,
        max_length: int | None = None,
        choices: Any = None,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        self.max_length = max_length
        super().__init__(
            choices=choices,
            required=required,
            allow_null=allow_null,
            default=default,
            validators=validators,
        )
        if self.max_length is not None:
            self.validators.append(MaxLengthValidator(self.max_length))

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.max_length is not None:
            kwargs["max_length"] = self.max_length
        return name, path, args, kwargs

    @property
    def description(self) -> str:
        if self.max_length is not None:
            return "String (up to %(max_length)s)"
        else:
            return "String (unlimited)"

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_max_length_attribute(),
        ]

    def _check_max_length_attribute(self, **kwargs: Any) -> list[PreflightResult]:
        if self.max_length is None:
            return []
        elif (
            not isinstance(self.max_length, int)
            or isinstance(self.max_length, bool)
            or self.max_length <= 0
        ):
            return [
                PreflightResult(
                    fix="'max_length' must be a positive integer.",
                    obj=self,
                    id="fields.textfield_invalid_max_length",
                )
            ]
        else:
            return []

    def _max_length_for_choices_check(self) -> int | None:
        return self.max_length

    def to_python(self, value: Any) -> str | None:
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)


class EmailField(TextField):
    default_validators = [validators.validate_email]


class URLField(TextField):
    default_validators = [validators.URLValidator()]


class RandomStringField(ColumnField[str]):
    """Text column whose value is a Postgres-generated random hex string.

    The column carries a ``DEFAULT`` that evaluates per row, so raw SQL and
    ORM inserts both get a fresh ``length``-character hex string. Pass an
    explicit value at ``create()`` time to override.
    """

    db_type_sql = "text"

    def __init__(
        self,
        *,
        length: int,
        required: bool = True,
        allow_null: bool = False,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        from plain.postgres.functions.random import RandomString

        self._expression = RandomString(length=length)
        super().__init__(
            required=required,
            allow_null=allow_null,
            validators=validators,
        )

    def get_db_default_expression(self) -> RandomString:
        return self._expression

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        kwargs["length"] = self._expression.length
        return name, path, args, kwargs
