"""
Type stubs for typed model fields.

These stubs tell type checkers that field constructors return primitive types,
enabling typed model definitions like:
    name: str = types.TextField()

At runtime, these are Field instances (descriptors), but type checkers see the primitives.

The return type is conditional on allow_null:
- allow_null=False (default) returns the primitive type (e.g., str)
- allow_null=True returns the primitive type | None (e.g., str | None)
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from json import JSONDecoder, JSONEncoder
from typing import Any, Literal, overload
from uuid import UUID
from zoneinfo import ZoneInfo

# Import manager types from runtime (will be Generic[T, QS] there)
from plain.postgres.base import Model
from plain.postgres.deletion import OnDelete
from plain.postgres.fields.related_managers import (
    ManyToManyManager,
    ReverseForeignKeyManager,
)
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
) -> str | None: ...
@overload
def TextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> str: ...
@overload
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> str | None: ...
@overload
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> str: ...
@overload
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> str | None: ...
@overload
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    validators: Sequence[Callable[..., Any]] = (),
) -> str: ...

# Integer fields
@overload
def IntegerField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> int | None: ...
@overload
def IntegerField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> int: ...
@overload
def BigIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> int | None: ...
@overload
def BigIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> int: ...
@overload
def SmallIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> int | None: ...
@overload
def SmallIntegerField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> int: ...
def PrimaryKeyField() -> int: ...

# Numeric fields
@overload
def FloatField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> float | None: ...
@overload
def FloatField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> float: ...
@overload
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> Decimal | None: ...
@overload
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> Decimal: ...

# Boolean field
@overload
def BooleanField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> bool | None: ...
@overload
def BooleanField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> bool: ...

# Date/time fields
@overload
def DateField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> date | None: ...
@overload
def DateField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> date: ...
@overload
def DateTimeField(
    *,
    create_now: bool = False,
    update_now: bool = False,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> datetime | None: ...
@overload
def DateTimeField(
    *,
    create_now: bool = False,
    update_now: bool = False,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> datetime: ...
@overload
def TimeField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> time | None: ...
@overload
def TimeField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> time: ...
@overload
def DurationField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> timedelta | None: ...
@overload
def DurationField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> timedelta: ...
@overload
def TimeZoneField(
    *,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> ZoneInfo | None: ...
@overload
def TimeZoneField(
    *,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> ZoneInfo: ...

# Other fields
@overload
def UUIDField(
    *,
    generate: bool = False,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> UUID | None: ...
@overload
def UUIDField(
    *,
    generate: bool = False,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> UUID: ...
@overload
def RandomStringField(
    *,
    length: int,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> str | None: ...
@overload
def RandomStringField(
    *,
    length: int,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> str: ...
@overload
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> bytes | None: ...
@overload
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> bytes: ...
@overload
def GenericIPAddressField(
    *,
    protocol: str = "both",
    unpack_ipv4: bool = False,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> str | None: ...
@overload
def GenericIPAddressField(
    *,
    protocol: str = "both",
    unpack_ipv4: bool = False,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> str: ...
@overload
def JSONField(
    *,
    encoder: type[JSONEncoder] | None = None,
    decoder: type[JSONDecoder] | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...
@overload
def JSONField(
    *,
    encoder: type[JSONEncoder] | None = None,
    decoder: type[JSONDecoder] | None = None,
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
) -> str | None: ...
@overload
def EncryptedTextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> str: ...
@overload
def EncryptedJSONField(
    *,
    encoder: type[JSONEncoder] | None = None,
    decoder: type[JSONDecoder] | None = None,
    required: bool = True,
    allow_null: Literal[True],
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...
@overload
def EncryptedJSONField(
    *,
    encoder: type[JSONEncoder] | None = None,
    decoder: type[JSONDecoder] | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    validators: Sequence[Callable[..., Any]] = (),
) -> Any: ...

# Related fields
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
) -> T | None: ...
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
) -> T: ...
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
