"""Type stubs for form fields.

These stubs tell type checkers that each field constructor returns a typed
`Field[T]` — a descriptor that yields the cleaned value `T` on a validated
form instance, and the field reference itself on the form class:

    class ContactForm(Form):
        email = types.EmailField()
        age   = types.IntegerField()

    ContactForm.email   # Field[str]  — the typed reference (keys a RequestForm)
    contact.email       # str         — the cleaned value

Return type is conditional on `required`:
- required=True (default) → Field[T]
- required=False          → Field[T | None]
"""

import re
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, overload
from uuid import UUID

from plain.internal.files.uploadedfile import UploadedFile

from .fields import Field

# Text fields
@overload
def TextField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
) -> Field[str | None]: ...
@overload
def TextField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
) -> Field[str]: ...
@overload
def EmailField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
) -> Field[str | None]: ...
@overload
def EmailField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
) -> Field[str]: ...
@overload
def URLField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
) -> Field[str | None]: ...
@overload
def URLField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = True,
    initial: Any = None,
) -> Field[str]: ...
@overload
def RegexField(
    regex: str | re.Pattern[str],
    *,
    required: Literal[False],
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = False,
    initial: Any = None,
) -> Field[str | None]: ...
@overload
def RegexField(
    regex: str | re.Pattern[str],
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    min_length: int | None = None,
    strip: bool = False,
    initial: Any = None,
) -> Field[str]: ...

# Numeric fields
@overload
def IntegerField(
    *,
    required: Literal[False],
    min_value: int | None = None,
    max_value: int | None = None,
    step_size: int | None = None,
    initial: Any = None,
) -> Field[int | None]: ...
@overload
def IntegerField(
    *,
    required: Literal[True] = True,
    min_value: int | None = None,
    max_value: int | None = None,
    step_size: int | None = None,
    initial: Any = None,
) -> Field[int]: ...
@overload
def FloatField(
    *,
    required: Literal[False],
    min_value: float | None = None,
    max_value: float | None = None,
    step_size: float | None = None,
    initial: Any = None,
) -> Field[float | None]: ...
@overload
def FloatField(
    *,
    required: Literal[True] = True,
    min_value: float | None = None,
    max_value: float | None = None,
    step_size: float | None = None,
    initial: Any = None,
) -> Field[float]: ...
@overload
def DecimalField(
    *,
    required: Literal[False],
    max_value: Decimal | int | None = None,
    min_value: Decimal | int | None = None,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    initial: Any = None,
) -> Field[Decimal | None]: ...
@overload
def DecimalField(
    *,
    required: Literal[True] = True,
    max_value: Decimal | int | None = None,
    min_value: Decimal | int | None = None,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    initial: Any = None,
) -> Field[Decimal]: ...

# Date / time fields
@overload
def DateField(
    *, required: Literal[False], initial: Any = None
) -> Field[date | None]: ...
@overload
def DateField(
    *, required: Literal[True] = True, initial: Any = None
) -> Field[date]: ...
@overload
def TimeField(
    *, required: Literal[False], initial: Any = None
) -> Field[time | None]: ...
@overload
def TimeField(
    *, required: Literal[True] = True, initial: Any = None
) -> Field[time]: ...
@overload
def DateTimeField(
    *, required: Literal[False], initial: Any = None
) -> Field[datetime | None]: ...
@overload
def DateTimeField(
    *, required: Literal[True] = True, initial: Any = None
) -> Field[datetime]: ...
@overload
def DurationField(
    *, required: Literal[False], initial: Any = None
) -> Field[timedelta | None]: ...
@overload
def DurationField(
    *, required: Literal[True] = True, initial: Any = None
) -> Field[timedelta]: ...

# Choice fields
@overload
def ChoiceField(
    *, choices: Any, required: Literal[False], initial: Any = None
) -> Field[str | None]: ...
@overload
def ChoiceField(
    *, choices: Any, required: Literal[True] = True, initial: Any = None
) -> Field[str]: ...
def TypedChoiceField[T](
    *,
    choices: Any,
    coerce: Callable[[Any], T],
    empty_value: Any = "",
    required: bool = True,
    initial: Any = None,
) -> Field[T]: ...
def MultipleChoiceField(
    *,
    choices: Any,
    required: bool = True,
    initial: Any = None,
) -> Field[list[str]]: ...

# Boolean fields
def BooleanField(
    *,
    required: bool = True,
    initial: Any = None,
) -> Field[bool]: ...
def NullBooleanField(
    *,
    required: bool = True,
    initial: Any = None,
) -> Field[bool | None]: ...

# Other
@overload
def UUIDField(
    *, required: Literal[False], initial: Any = None
) -> Field[UUID | None]: ...
@overload
def UUIDField(
    *, required: Literal[True] = True, initial: Any = None
) -> Field[UUID]: ...
def JSONField(
    *,
    required: bool = True,
    initial: Any = None,
) -> Field[Any]: ...

# File fields — return UploadedFile (or None when required=False).
@overload
def FileField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    allow_empty_file: bool = False,
    initial: Any = None,
) -> Field[UploadedFile | None]: ...
@overload
def FileField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    allow_empty_file: bool = False,
    initial: Any = None,
) -> Field[UploadedFile]: ...
@overload
def ImageField(
    *,
    required: Literal[False],
    max_length: int | None = None,
    initial: Any = None,
) -> Field[UploadedFile | None]: ...
@overload
def ImageField(
    *,
    required: Literal[True] = True,
    max_length: int | None = None,
    initial: Any = None,
) -> Field[UploadedFile]: ...
