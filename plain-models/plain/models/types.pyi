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
from typing import Any, Literal, TypeVar, overload
from uuid import UUID

# TypeVar for generic ForeignKey/ManyToManyField support
_T = TypeVar("_T")

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
def ForeignKey(
    to: type[_T],
    on_delete: Any,
    *,
    related_name: str | None = None,
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
def ForeignKey(
    to: type[_T],
    on_delete: Any,
    *,
    related_name: str | None = None,
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
    to: type[_T],
    *,
    through: Any,
    through_fields: tuple[str, str] | None = None,
    related_name: str | None = None,
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
) -> Any: ...
