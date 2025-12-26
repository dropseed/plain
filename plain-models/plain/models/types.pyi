"""
Type stubs for typed model fields.

These stubs tell type checkers that field constructors return primitive types,
enabling typed model definitions like:
    name: str = types.CharField()

At runtime, these are Field instances (descriptors), but type checkers see the primitives.

The return type is conditional on allow_null:
- allow_null=False (default) returns the primitive type (e.g., str)
- allow_null=True returns the primitive type | None (e.g., str | None)
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from json import JSONDecoder, JSONEncoder
from typing import Any, Generic, Literal, TypeVar, overload
from uuid import UUID
from zoneinfo import ZoneInfo

# Import manager types from runtime (will be Generic[T, QS] there)
from plain.models.base import Model
from plain.models.fields.related_managers import (
    ManyToManyManager,
    ReverseForeignKeyManager,
)
from plain.models.query import QuerySet

# TypeVar for generic ForeignKey/ManyToManyField support
_T = TypeVar("_T", bound=Model)
# TypeVar for custom QuerySet types (defaults to QuerySet[Any] when not specified)
_QS = TypeVar("_QS", bound=QuerySet[Any], default=QuerySet[Any])

# String fields
@overload
def CharField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str | None: ...
@overload
def CharField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
@overload
def TextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str | None: ...
@overload
def TextField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
@overload
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str | None: ...
@overload
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
@overload
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str | None: ...
@overload
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    db_collation: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...

# Integer fields
@overload
def IntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def IntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
@overload
def BigIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def BigIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
@overload
def SmallIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def SmallIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
@overload
def PositiveIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def PositiveIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
@overload
def PositiveBigIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def PositiveBigIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
@overload
def PositiveSmallIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def PositiveSmallIntegerField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
@overload
def PrimaryKeyField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int | None: ...
@overload
def PrimaryKeyField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...

# Numeric fields
@overload
def FloatField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> float | None: ...
@overload
def FloatField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> float: ...
@overload
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> Decimal | None: ...
@overload
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> Decimal: ...

# Boolean field
@overload
def BooleanField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> bool | None: ...
@overload
def BooleanField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> bool: ...

# Date/time fields
@overload
def DateField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> date | None: ...
@overload
def DateField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> date: ...
@overload
def DateTimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> datetime | None: ...
@overload
def DateTimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> datetime: ...
@overload
def TimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> time | None: ...
@overload
def TimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> time: ...
@overload
def DurationField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> timedelta | None: ...
@overload
def DurationField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> timedelta: ...
@overload
def TimeZoneField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> ZoneInfo | None: ...
@overload
def TimeZoneField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> ZoneInfo: ...

# Other fields
@overload
def UUIDField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> UUID | None: ...
@overload
def UUIDField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> UUID: ...
@overload
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> bytes | None: ...
@overload
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> bytes: ...
@overload
def GenericIPAddressField(
    *,
    protocol: str = "both",
    unpack_ipv4: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str | None: ...
@overload
def GenericIPAddressField(
    *,
    protocol: str = "both",
    unpack_ipv4: bool = False,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
@overload
def JSONField(
    *,
    encoder: type[JSONEncoder] | None = None,
    decoder: type[JSONDecoder] | None = None,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> Any: ...
@overload
def JSONField(
    *,
    encoder: type[JSONEncoder] | None = None,
    decoder: type[JSONDecoder] | None = None,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> Any: ...

# Related fields
@overload
def ForeignKeyField(
    to: type[_T] | str,
    on_delete: Any,
    *,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    db_index: bool = True,
    db_constraint: bool = True,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[True],
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> _T | None: ...
@overload
def ForeignKeyField(
    to: type[_T] | str,
    on_delete: Any,
    *,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    db_index: bool = True,
    db_constraint: bool = True,
    max_length: int | None = None,
    required: bool = True,
    allow_null: Literal[False] = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> _T: ...
def ManyToManyField(
    to: type[_T] | str,
    *,
    through: Any,
    through_fields: tuple[str, str] | None = None,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    symmetrical: bool | None = None,
    max_length: int | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = ...,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> ManyToManyManager[_T]: ...

# Reverse relation descriptors
class ReverseForeignKey(Generic[_T, _QS]):
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
    def __init__(self, *, to: type[_T] | str, field: str) -> None: ...
    @overload
    def __get__(self, instance: None, owner: type) -> ReverseForeignKey[_T, _QS]: ...
    @overload
    def __get__(
        self, instance: Model, owner: type
    ) -> ReverseForeignKeyManager[_T, _QS]: ...
    def __get__(
        self, instance: Model | None, owner: type
    ) -> ReverseForeignKey[_T, _QS] | ReverseForeignKeyManager[_T, _QS]: ...

class ReverseManyToMany(Generic[_T, _QS]):
    """
    Descriptor for the reverse side of a ManyToManyField.

    Type parameters:
        _T: The related model type
        _QS: The QuerySet type (use the model's custom QuerySet for proper method typing)
    """
    def __init__(self, *, to: type[_T] | str, field: str) -> None: ...
    @overload
    def __get__(self, instance: None, owner: type) -> ReverseManyToMany[_T, _QS]: ...
    @overload
    def __get__(self, instance: Model, owner: type) -> ManyToManyManager[_T, _QS]: ...
    def __get__(
        self, instance: Model | None, owner: type
    ) -> ReverseManyToMany[_T, _QS] | ManyToManyManager[_T, _QS]: ...

# Export all types (should match types.py)
__all__ = [
    "BigIntegerField",
    "BinaryField",
    "BooleanField",
    "CharField",
    "DateField",
    "DateTimeField",
    "DecimalField",
    "DurationField",
    "EmailField",
    "FloatField",
    "ForeignKeyField",
    "GenericIPAddressField",
    "IntegerField",
    "JSONField",
    "ManyToManyField",
    "ManyToManyManager",
    "PositiveBigIntegerField",
    "PositiveIntegerField",
    "PositiveSmallIntegerField",
    "PrimaryKeyField",
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
