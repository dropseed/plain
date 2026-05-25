"""
Type stubs for typed model fields.

These stubs tell type checkers that each field constructor returns the
typed *descriptor* (`XField[T]`), not the primitive `T`. Combined with
`Field.__get__`'s overloads, this gives you:

    class User(postgres.Model):
        email = types.EmailField()
        age = types.IntegerField(allow_null=True)

    User.email   # EmailField[str]        — typed reference, has .equals(), .contains(), ...
    user.email   # str                    — the loaded value
    User.age     # IntegerField[int | None]
    user.age     # int | None

The return type is parameterized by nullability:
- allow_null=False (default) → XField[T]
- allow_null=True            → XField[T | None]
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, overload
from uuid import UUID
from zoneinfo import ZoneInfo

from plain.postgres.base import Model
from plain.postgres.deletion import OnDelete
from plain.postgres.fields.binary import BinaryField as _BinaryField
from plain.postgres.fields.boolean import BooleanField as _BooleanField
from plain.postgres.fields.duration import DurationField as _DurationField
from plain.postgres.fields.encrypted import EncryptedTextField as _EncryptedTextField
from plain.postgres.fields.network import (
    GenericIPAddressField as _GenericIPAddressField,
)
from plain.postgres.fields.numeric import BigIntegerField as _BigIntegerField
from plain.postgres.fields.numeric import DecimalField as _DecimalField
from plain.postgres.fields.numeric import FloatField as _FloatField
from plain.postgres.fields.numeric import IntegerField as _IntegerField
from plain.postgres.fields.numeric import SmallIntegerField as _SmallIntegerField
from plain.postgres.fields.primary_key import PrimaryKeyField as _PrimaryKeyField
from plain.postgres.fields.related_managers import (
    ManyToManyManager,
    ReverseForeignKeyManager,
)
from plain.postgres.fields.temporal import DateField as _DateField
from plain.postgres.fields.temporal import DateTimeField as _DateTimeField
from plain.postgres.fields.temporal import TimeField as _TimeField
from plain.postgres.fields.text import EmailField as _EmailField
from plain.postgres.fields.text import RandomStringField as _RandomStringField
from plain.postgres.fields.text import TextField as _TextField
from plain.postgres.fields.text import URLField as _URLField
from plain.postgres.fields.timezones import TimeZoneField as _TimeZoneField
from plain.postgres.fields.uuid import UUIDField as _UUIDField
from plain.postgres.query import QuerySet

# String fields
@overload
def TextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> _TextField[str | None]: ...
@overload
def TextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> _TextField[str]: ...
@overload
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> _EmailField[str | None]: ...
@overload
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> _EmailField[str]: ...
@overload
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> _URLField[str | None]: ...
@overload
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> _URLField[str]: ...

# Integer fields
@overload
def IntegerField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _IntegerField[int | None]: ...
@overload
def IntegerField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _IntegerField[int]: ...
@overload
def BigIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _BigIntegerField[int | None]: ...
@overload
def BigIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _BigIntegerField[int]: ...
@overload
def SmallIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _SmallIntegerField[int | None]: ...
@overload
def SmallIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _SmallIntegerField[int]: ...
def PrimaryKeyField() -> _PrimaryKeyField: ...

# Numeric fields
@overload
def FloatField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _FloatField[float | None]: ...
@overload
def FloatField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _FloatField[float]: ...
@overload
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DecimalField[Decimal | None]: ...
@overload
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DecimalField[Decimal]: ...

# Boolean field
@overload
def BooleanField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _BooleanField[bool | None]: ...
@overload
def BooleanField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _BooleanField[bool]: ...

# Date/time fields
@overload
def DateField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DateField[date | None]: ...
@overload
def DateField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DateField[date]: ...
@overload
def DateTimeField(
    *,
    create_now: bool = False,
    update_now: bool = False,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> _DateTimeField[datetime | None]: ...
@overload
def DateTimeField(
    *,
    create_now: bool = False,
    update_now: bool = False,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DateTimeField[datetime]: ...
@overload
def TimeField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _TimeField[time | None]: ...
@overload
def TimeField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _TimeField[time]: ...
@overload
def DurationField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DurationField[timedelta | None]: ...
@overload
def DurationField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _DurationField[timedelta]: ...
@overload
def TimeZoneField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _TimeZoneField[ZoneInfo | None]: ...
@overload
def TimeZoneField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _TimeZoneField[ZoneInfo]: ...

# Other fields
@overload
def UUIDField(
    *,
    generate: bool = False,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> _UUIDField[UUID | None]: ...
@overload
def UUIDField(
    *,
    generate: bool = False,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> _UUIDField[UUID]: ...
@overload
def RandomStringField(
    *,
    length: int,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> _RandomStringField[str | None]: ...
@overload
def RandomStringField(
    *,
    length: int,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> _RandomStringField[str]: ...
@overload
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> _BinaryField[bytes | memoryview | None]: ...
@overload
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> _BinaryField[bytes | memoryview]: ...
@overload
def GenericIPAddressField(
    *,
    protocol: str = "both",
    unpack_ipv4: bool = False,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _GenericIPAddressField[str | None]: ...
@overload
def GenericIPAddressField(
    *,
    protocol: str = "both",
    unpack_ipv4: bool = False,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> _GenericIPAddressField[str]: ...
@overload
def JSONField(
    *,
    encoder: Any = None,
    decoder: Any = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...
@overload
def JSONField(
    *,
    encoder: Any = None,
    decoder: Any = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...

# Encrypted fields
@overload
def EncryptedTextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> _EncryptedTextField[str | None]: ...
@overload
def EncryptedTextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> _EncryptedTextField[str]: ...
@overload
def EncryptedJSONField(
    *,
    encoder: Any = None,
    decoder: Any = None,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...
@overload
def EncryptedJSONField(
    *,
    encoder: Any = None,
    decoder: Any = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...

# Related fields
#
# At the type level, the ForeignKeyField stub returns a descriptor whose
# `__get__` overloads do double duty:
#   * Class access (User.parent) → type[T] so the related model's typed
#     field surface (e.g. `User.parent.name.equals(...)`) is visible to
#     the type checker for typed where() chaining.
#   * Instance access (user.parent) → T (or T | None for nullable FKs) so
#     reading the loaded related instance has the value type.
# The runtime is a Field instance + a ForwardForeignKeyDescriptor, which
# is structurally compatible — only the typing-side shape differs.
class _ForeignKeyDescriptor[T: Model, V]:
    @overload
    def __get__(self, instance: None, owner: type) -> type[T]: ...
    @overload
    def __get__(self, instance: Model, owner: type) -> V: ...
    def __set__(self, instance: Model, value: V | int) -> None: ...

@overload
def ForeignKeyField[T: Model](
    to: type[T] | str,
    on_delete: OnDelete,
    *,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    db_constraint: bool = True,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> _ForeignKeyDescriptor[T, T | None]: ...
@overload
def ForeignKeyField[T: Model](
    to: type[T] | str,
    on_delete: OnDelete,
    *,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    db_constraint: bool = True,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> _ForeignKeyDescriptor[T, T]: ...
def ManyToManyField[T: Model](
    to: type[T] | str,
    *,
    through: Any,
    through_fields: tuple[str, str] | None = None,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    symmetrical: bool | None = None,
) -> ManyToManyManager[T]: ...

# Reverse relation descriptors
class ReverseForeignKey[T: Model, QS: QuerySet[Any] = QuerySet[Any]]:
    """
    Descriptor for the reverse side of a ForeignKeyField.

    Type parameters:
        _T: The related model type
        _QS: The QuerySet type (use the model's custom QuerySet for proper method typing)

    Example:
        # With custom QuerySet for proper typing of custom methods like .enabled()
        repos: ReverseForeignKey[Repo, RepoQuerySet] = ReverseForeignKey(to="Repo", field="organization")

        # Usage: org.repos.query.enabled()  # .enabled() is now recognized
    """
    def __init__(self, *, to: type[T] | str, field: str) -> None: ...
    @overload
    def __get__(self, instance: None, owner: type) -> ReverseForeignKey[T, QS]: ...
    @overload
    def __get__(
        self, instance: Model, owner: type
    ) -> ReverseForeignKeyManager[T, QS]: ...
    def __get__(
        self, instance: Model | None, owner: type
    ) -> ReverseForeignKey[T, QS] | ReverseForeignKeyManager[T, QS]: ...

class ReverseManyToMany[T: Model, QS: QuerySet[Any] = QuerySet[Any]]:
    """
    Descriptor for the reverse side of a ManyToManyField.

    Type parameters:
        _T: The related model type
        _QS: The QuerySet type (use the model's custom QuerySet for proper method typing)
    """
    def __init__(self, *, to: type[T] | str, field: str) -> None: ...
    @overload
    def __get__(self, instance: None, owner: type) -> ReverseManyToMany[T, QS]: ...
    @overload
    def __get__(self, instance: Model, owner: type) -> ManyToManyManager[T, QS]: ...
    def __get__(
        self, instance: Model | None, owner: type
    ) -> ReverseManyToMany[T, QS] | ManyToManyManager[T, QS]: ...

# Export all types (should match types.py)
__all__ = [
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "EncryptedJSONField",
    "EncryptedTextField",
    "FloatField",
    "ForeignKeyField",
    "GenericIPAddressField",
    "IntegerField",
    "JSONField",
    "ManyToManyField",
    "ManyToManyManager",
    "PrimaryKeyField",
    "RandomStringField",
    "ReverseForeignKey",
    "ReverseForeignKeyManager",
    "ReverseManyToMany",
    "SmallIntegerField",
    "TextField",
    "TimeField",
    "TimeZoneField",
    "URLField",
    "UUIDField",
]
