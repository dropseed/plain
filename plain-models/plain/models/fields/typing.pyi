"""Type checking overrides for field constructors.

This module provides function signature overrides that make field constructors
appear to return their value types (str, int, etc.) instead of Field instances.
This enables natural type-annotated model syntax like: name: str = CharField()

User code imports via plain.models which applies these overrides under TYPE_CHECKING.
"""

from __future__ import annotations

import datetime
import decimal
import json
import uuid
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

# Sentinel value for "not provided" - match the actual implementation
NOT_PROVIDED = TypeVar("NOT_PROVIDED")

# Generic type for related model
_T = TypeVar("_T")

__all__ = [
    "CharField",
    "IntegerField",
    "BooleanField",
    "DateTimeField",
    "TextField",
    "EmailField",
    "URLField",
    "GenericIPAddressField",
    "DateField",
    "TimeField",
    "FloatField",
    "DecimalField",
    "DurationField",
    "UUIDField",
    "BinaryField",
    "BigIntegerField",
    "SmallIntegerField",
    "PositiveIntegerField",
    "PositiveBigIntegerField",
    "PositiveSmallIntegerField",
    "PrimaryKeyField",
    "JSONField",
    "ForeignKey",
    "ManyToManyField",
]

def CharField(
    *,
    max_length: int | None = None,
    db_collation: str | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
def IntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def BooleanField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> bool: ...
def DateTimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> datetime.datetime: ...
def TextField(
    *,
    db_collation: str | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
def EmailField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
def URLField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
def GenericIPAddressField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> str: ...
def DateField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> datetime.date: ...
def TimeField(
    *,
    auto_now: bool = False,
    auto_now_add: bool = False,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> datetime.time: ...
def FloatField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> float: ...
def DecimalField(
    *,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> decimal.Decimal: ...
def DurationField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> datetime.timedelta: ...
def UUIDField(
    *,
    primary_key: bool = False,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> uuid.UUID: ...
def BinaryField(
    *,
    max_length: int | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> bytes | memoryview: ...
def BigIntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def SmallIntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def PositiveIntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def PositiveBigIntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def PositiveSmallIntegerField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    choices: Any = None,
    db_column: str | None = None,
    validators: Sequence[Callable[..., Any]] = (),
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def PrimaryKeyField(
    *,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> int: ...
def JSONField(
    *,
    encoder: type[json.JSONEncoder] | None = None,
    decoder: type[json.JSONDecoder] | None = None,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> Any: ...
def ForeignKey(
    to: type[_T] | str,
    on_delete: Any,
    *,
    related_name: str | None = None,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    db_index: bool = True,
    db_constraint: bool = True,
    required: bool = True,
    allow_null: bool = False,
    default: Any = NOT_PROVIDED,
    db_column: str | None = None,
    error_messages: dict[str, str] | None = None,
    db_comment: str | None = None,
) -> _T: ...
def ManyToManyField(
    to: type[_T] | str,
    *,
    related_name: str | None = None,
    related_query_name: str | None = None,
    limit_choices_to: Any = None,
    through: type[Any] | str | None = None,
    through_fields: tuple[str, str] | None = None,
    db_table: str | None = None,
    db_constraint: bool = True,
    db_comment: str | None = None,
) -> Any: ...
