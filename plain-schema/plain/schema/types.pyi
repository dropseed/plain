"""Type stubs for schema fields.

These stubs tell type checkers that field constructors return their cleaned
Python type, enabling typed schema definitions like:

    class ContactSchema(Schema):
        email: str = fields.EmailField()
        age: int = fields.IntegerField()

At runtime these are Field instances; the type checker sees the primitives.

Return type is conditional on `required`:
- required=True (default) → returns T
- required=False → returns T | None
"""

from collections.abc import Callable, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, overload
from uuid import UUID

from plain.internal.files.uploadedfile import UploadedFile

# Text fields
@overload
def TextField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str | None: ...
@overload
def TextField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str: ...
@overload
def EmailField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    min_length: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str | None: ...
@overload
def EmailField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    min_length: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str: ...
@overload
def URLField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str | None: ...
@overload
def URLField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str: ...
@overload
def RegexField(
    regex: str,
    *,
    required: Literal[False],
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str | None: ...
@overload
def RegexField(
    regex: str,
    *,
    required: Literal[True] = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str: ...

# Numeric fields
@overload
def IntegerField(
    *,
    required: Literal[False],
    min_value: int | None = None,
    max_value: int | None = None,
    step_size: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> int | None: ...
@overload
def IntegerField(
    *,
    required: Literal[True] = True,
    min_value: int | None = None,
    max_value: int | None = None,
    step_size: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> int: ...
@overload
def FloatField(
    *,
    required: Literal[False],
    min_value: float | None = None,
    max_value: float | None = None,
    step_size: float | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> float | None: ...
@overload
def FloatField(
    *,
    required: Literal[True] = True,
    min_value: float | None = None,
    max_value: float | None = None,
    step_size: float | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> float: ...
@overload
def DecimalField(
    *,
    required: Literal[False],
    max_value: Decimal | None = None,
    min_value: Decimal | None = None,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    step_size: Decimal | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> Decimal | None: ...
@overload
def DecimalField(
    *,
    required: Literal[True] = True,
    max_value: Decimal | None = None,
    min_value: Decimal | None = None,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    step_size: Decimal | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> Decimal: ...

# Date / time fields
@overload
def DateField(
    *,
    required: Literal[False],
    input_formats: Sequence[str] | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> date | None: ...
@overload
def DateField(
    *,
    required: Literal[True] = True,
    input_formats: Sequence[str] | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> date: ...
@overload
def TimeField(
    *,
    required: Literal[False],
    input_formats: Sequence[str] | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> time | None: ...
@overload
def TimeField(
    *,
    required: Literal[True] = True,
    input_formats: Sequence[str] | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> time: ...
@overload
def DateTimeField(
    *,
    required: Literal[False],
    input_formats: Sequence[str] | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> datetime | None: ...
@overload
def DateTimeField(
    *,
    required: Literal[True] = True,
    input_formats: Sequence[str] | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> datetime: ...
@overload
def DurationField(
    *,
    required: Literal[False],
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> timedelta | None: ...
@overload
def DurationField(
    *,
    required: Literal[True] = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> timedelta: ...

# Choice fields
@overload
def ChoiceField(
    *,
    choices: Any,
    required: Literal[False],
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str | None: ...
@overload
def ChoiceField(
    *,
    choices: Any,
    required: Literal[True] = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> str: ...
@overload
def TypedChoiceField(
    *,
    choices: Any,
    coerce: Callable[[Any], Any] = ...,
    empty_value: Any = "",
    required: Literal[False],
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> Any: ...
@overload
def TypedChoiceField(
    *,
    choices: Any,
    coerce: Callable[[Any], Any] = ...,
    empty_value: Any = "",
    required: Literal[True] = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> Any: ...
def MultipleChoiceField(
    *,
    choices: Any,
    required: bool = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> list[str]: ...

# Boolean fields
@overload
def BooleanField(
    *,
    required: Literal[False] = False,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> bool: ...
@overload
def BooleanField(
    *,
    required: Literal[True],
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> bool: ...
def NullBooleanField(
    *,
    required: bool = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> bool | None: ...

# Other
@overload
def UUIDField(
    *,
    required: Literal[False],
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> UUID | None: ...
@overload
def UUIDField(
    *,
    required: Literal[True] = True,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> UUID: ...
def JSONField(
    *,
    required: bool = True,
    encoder: Any = None,
    decoder: Any = None,
    indent: int | None = None,
    sort_keys: bool = False,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> Any: ...

# File fields — return UploadedFile (or None when required=False).
@overload
def FileField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    allow_empty_file: bool = False,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> UploadedFile | None: ...
@overload
def FileField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    allow_empty_file: bool = False,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> UploadedFile: ...
@overload
def ImageField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> UploadedFile | None: ...
@overload
def ImageField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    initial: Any = None,
    error_messages: dict[str, str] | None = None,
    validators: Sequence[Callable[[Any], None]] = (),
) -> UploadedFile: ...
