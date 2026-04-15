from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from plain import exceptions
from plain.postgres.dialect import adapt_ipaddressfield_value
from plain.preflight import PreflightResult
from plain.utils.ipv6 import clean_ipv6_address
from plain.validators import ip_address_validators

from .base import NOT_PROVIDED, DefaultableField

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


class GenericIPAddressField(DefaultableField[str]):
    db_type_sql = "inet"
    empty_strings_allowed = False
    default_error_messages = {}

    def __init__(
        self,
        *,
        protocol: str = "both",
        unpack_ipv4: bool = False,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
        error_messages: dict[str, str] | None = None,
    ):
        self.unpack_ipv4 = unpack_ipv4
        self.protocol = protocol
        (
            self.default_validators,
            invalid_error_message,
        ) = ip_address_validators(protocol, unpack_ipv4)
        self.default_error_messages["invalid"] = invalid_error_message
        super().__init__(
            required=required,
            allow_null=allow_null,
            default=default,
            validators=validators,
            error_messages=error_messages,
        )

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_required_and_null_values(),
        ]

    def _check_required_and_null_values(self) -> list[PreflightResult]:
        if not getattr(self, "allow_null", False) and not getattr(
            self, "required", True
        ):
            return [
                PreflightResult(
                    fix="GenericIPAddressFields cannot have required=False if allow_null=False, "
                    "as blank values are stored as nulls.",
                    obj=self,
                    id="fields.generic_ip_field_null_blank_config",
                )
            ]
        return []

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.unpack_ipv4 is not False:
            kwargs["unpack_ipv4"] = self.unpack_ipv4
        if self.protocol != "both":
            kwargs["protocol"] = self.protocol
        return name, path, args, kwargs

    def to_python(self, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if ":" in value:
            return clean_ipv6_address(
                value, self.unpack_ipv4, self.error_messages["invalid"]
            )
        return value

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return adapt_ipaddressfield_value(value)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value is None:
            return None
        if value and ":" in value:
            try:
                return clean_ipv6_address(value, self.unpack_ipv4)
            except exceptions.ValidationError:
                pass
        return str(value)
