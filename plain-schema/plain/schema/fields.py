"""Field classes — the validating parsers behind schema declarations.

Each field turns one raw value into a cleaned, typed Python value via
`clean()`, raising `plain.exceptions.ValidationError` on bad input. Fields
are pure validators: no widgets, no HTML, no form/request binding — that's
what keeps `plain.schema` independent of `plain.forms`.

The companion `types.pyi` stub types each constructor as returning a
`Field[T]` descriptor, so a declaration like `email: Field[str] =
EmailField()` type-checks — and `ContactSchema.email` resolves to the
typed reference while `instance.email` resolves to the cleaned value.
"""

from __future__ import annotations

import datetime
import enum
import json
import math
import re
import uuid
from collections.abc import Callable
from decimal import Decimal, DecimalException
from io import BytesIO
from typing import Any, Self, overload
from urllib.parse import urlsplit, urlunsplit

from plain import validators
from plain.exceptions import ValidationError
from plain.utils.dateparse import parse_date, parse_datetime, parse_duration, parse_time

__all__ = (
    "Field",
    "TextField",
    "EmailField",
    "URLField",
    "RegexField",
    "IntegerField",
    "FloatField",
    "DecimalField",
    "BooleanField",
    "NullBooleanField",
    "ChoiceField",
    "TypedChoiceField",
    "MultipleChoiceField",
    "DateField",
    "TimeField",
    "DateTimeField",
    "DurationField",
    "UUIDField",
    "JSONField",
    "FileField",
    "ImageField",
)

# Values that count as "no input" — an empty one fails a required field.
EMPTY_VALUES = validators.EMPTY_VALUES

REQUIRED_MESSAGE = "This field is required."


class Field[T]:
    """Base validating parser — and a descriptor for typed field access.

    `clean()` runs `parse()` (raw → typed Python value), enforces `required`,
    then runs any constraint validators. Subclasses override `parse()` and
    append validators in `__init__`.

    A field declared on a `Schema` is also a (non-data) descriptor with two
    faces:

      * accessed on the class — `ContactSchema.email` — it returns itself,
        the typed *reference* used to key a `BoundSchema`;
      * accessed on a validated instance — `contact.email` — it returns the
        cleaned *value* of type `T`, which `Schema.__init__` stored in the
        instance `__dict__`.

    Defining only `__get__` (no `__set__`) keeps it a non-data descriptor,
    so the value in the instance `__dict__` is what's actually read.
    """

    # Validators every instance of this field type runs. Subclasses set a
    # class-level list; __init__ copies it so per-instance appends are safe.
    default_validators: list[Callable[[Any], None]] = []

    # True for fields whose raw input is a list of values rather than one —
    # `Schema.validate` reads them with `.getlist()` from multi-valued data.
    multi_value: bool = False

    # The attribute name the field is declared under; set by `__set_name__`.
    name: str = ""

    def __init__(self, *, required: bool = True, initial: Any = None) -> None:
        self.required = required
        self.initial = initial
        self.validators: list[Callable[[Any], None]] = list(self.default_validators)

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, obj: None, owner: type) -> Self: ...
    @overload
    def __get__(self, obj: object, owner: type | None = None) -> T: ...
    def __get__(self, obj: object | None, owner: type | None = None) -> Self | T:
        if obj is None:
            return self  # class access → the typed reference
        try:
            return obj.__dict__[self.name]  # instance access → the cleaned value
        except KeyError:
            raise AttributeError(self.name) from None

    def parse(self, value: Any) -> Any:
        """Coerce a raw value to this field's Python type. Empty input
        returns an empty value rather than raising."""
        return value

    def clean(self, value: Any) -> Any:
        value = self.parse(value)
        if self._is_missing(value):
            return value
        self._run_validators(value)
        return value

    def _is_missing(self, value: Any) -> bool:
        """Return True when `value` is empty. Raise if empty isn't allowed."""
        if value in EMPTY_VALUES:
            if self.required:
                raise ValidationError(REQUIRED_MESSAGE, code="required")
            return True
        return False

    def _run_validators(self, value: Any) -> None:
        """Run every constraint validator, collecting all failures."""
        errors: list[ValidationError] = []
        for validator in self.validators:
            try:
                validator(value)
            except ValidationError as error:
                errors.extend(error.error_list)
        if errors:
            raise ValidationError(errors)


class TextField(Field[str]):
    """A string field with optional length bounds."""

    def __init__(
        self,
        *,
        max_length: int | None = None,
        min_length: int | None = None,
        strip: bool = True,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(required=required, initial=initial)
        self.max_length = max_length
        self.min_length = min_length
        self.strip = strip
        if min_length is not None:
            self.validators.append(validators.MinLengthValidator(min_length))
        if max_length is not None:
            self.validators.append(validators.MaxLengthValidator(max_length))
        self.validators.append(validators.ProhibitNullCharactersValidator())

    def parse(self, value: Any) -> str:
        if value in EMPTY_VALUES:
            return ""
        value = str(value)
        if self.strip:
            value = value.strip()
        return value


class EmailField(TextField):
    default_validators: list[Callable[[Any], None]] = [validators.validate_email]


class URLField(TextField):
    default_validators: list[Callable[[Any], None]] = [validators.URLValidator()]

    def parse(self, value: Any) -> str:
        value = super().parse(value)
        if not value:
            return value
        try:
            parts = list(urlsplit(value))
        except ValueError:
            raise ValidationError("Enter a valid URL.", code="invalid")
        if not parts[0]:
            # No scheme — assume http.
            parts[0] = "http"
        if not parts[1]:
            # No host — the path segment is carrying the domain.
            parts[1], parts[2] = parts[2], ""
            parts = list(urlsplit(urlunsplit(parts)))
        return urlunsplit(parts)


class RegexField(TextField):
    def __init__(
        self,
        regex: str | re.Pattern[str],
        *,
        max_length: int | None = None,
        min_length: int | None = None,
        strip: bool = False,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(
            max_length=max_length,
            min_length=min_length,
            strip=strip,
            required=required,
            initial=initial,
        )
        self.regex = re.compile(regex) if isinstance(regex, str) else regex
        self.validators.append(validators.RegexValidator(regex=self.regex))


class NumericField[T](Field[T]):
    """Base for numeric fields with min/max/step bounds."""

    def __init__(
        self,
        *,
        max_value: int | float | Decimal | None = None,
        min_value: int | float | Decimal | None = None,
        step_size: int | float | Decimal | None = None,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(required=required, initial=initial)
        self.max_value = max_value
        self.min_value = min_value
        self.step_size = step_size
        if min_value is not None:
            self.validators.append(validators.MinValueValidator(min_value))
        if max_value is not None:
            self.validators.append(validators.MaxValueValidator(max_value))
        if step_size is not None:
            self.validators.append(validators.StepValueValidator(step_size))


class IntegerField(NumericField[int]):
    _trailing_decimal = re.compile(r"\.0*\s*$")

    def parse(self, value: Any) -> int | None:
        if value in EMPTY_VALUES:
            return None
        try:
            return int(self._trailing_decimal.sub("", str(value)))
        except (TypeError, ValueError):
            raise ValidationError("Enter a whole number.", code="invalid")


class FloatField(NumericField[float]):
    def parse(self, value: Any) -> float | None:
        if value in EMPTY_VALUES:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValidationError("Enter a number.", code="invalid")
        if not math.isfinite(value):
            raise ValidationError("Enter a number.", code="invalid")
        return value


class DecimalField(NumericField[Decimal]):
    def __init__(
        self,
        *,
        max_value: Decimal | int | None = None,
        min_value: Decimal | int | None = None,
        max_digits: int | None = None,
        decimal_places: int | None = None,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(
            max_value=max_value,
            min_value=min_value,
            required=required,
            initial=initial,
        )
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        self.validators.append(validators.DecimalValidator(max_digits, decimal_places))

    def parse(self, value: Any) -> Decimal | None:
        if value in EMPTY_VALUES:
            return None
        try:
            value = Decimal(str(value))
        except DecimalException:
            raise ValidationError("Enter a number.", code="invalid")
        if not value.is_finite():
            raise ValidationError("Enter a number.", code="invalid")
        return value


class BooleanField(Field[bool]):
    def parse(self, value: Any) -> bool:
        # A hidden input submits the string "False" for an unchecked box.
        if isinstance(value, str) and value.lower() in ("false", "0"):
            return False
        return bool(value)

    def clean(self, value: Any) -> bool:
        value = self.parse(value)
        # `required` here means "must be true" (a checkbox that must be ticked).
        if not value and self.required:
            raise ValidationError(REQUIRED_MESSAGE, code="required")
        return value


class NullBooleanField(Field[bool | None]):
    """A boolean that also accepts `None` — never fails the required check."""

    def parse(self, value: Any) -> bool | None:
        if value in (True, "True", "true", "1"):
            return True
        if value in (False, "False", "false", "0"):
            return False
        return None

    def clean(self, value: Any) -> bool | None:
        return self.parse(value)


class _ChoiceField[T](Field[T]):
    """Shared choices handling for ChoiceField and MultipleChoiceField.

    They're siblings, not parent/child: one cleans to `str`, the other to
    `list[str]`, so neither can stand in for the other.
    """

    def __init__(
        self,
        *,
        choices: Any,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(required=required, initial=initial)
        if hasattr(choices, "choices"):
            choices = choices.choices
        elif isinstance(choices, enum.EnumMeta):
            choices = [(member.value, member.name) for member in choices]
        self.choices = list(choices)

    def _valid_choice(self, value: Any) -> bool:
        text_value = str(value)
        for key, label in self.choices:
            if isinstance(label, list | tuple):
                # An optgroup — look inside the group for options.
                for sub_key, _ in label:
                    if value == sub_key or text_value == str(sub_key):
                        return True
            elif value == key or text_value == str(key):
                return True
        return False


class ChoiceField(_ChoiceField[str]):
    def parse(self, value: Any) -> str:
        if value in EMPTY_VALUES:
            return ""
        return str(value)

    def clean(self, value: Any) -> str:
        value = self.parse(value)
        if self._is_missing(value):
            return value
        if not self._valid_choice(value):
            raise ValidationError(
                f"Select a valid choice. {value} is not one of the available choices.",
                code="invalid_choice",
            )
        return value


class TypedChoiceField(ChoiceField):
    def __init__(
        self,
        *,
        coerce: Callable[[Any], Any] = lambda value: value,
        empty_value: Any = "",
        choices: Any,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(choices=choices, required=required, initial=initial)
        self.coerce = coerce
        self.empty_value = empty_value

    def clean(self, value: Any) -> Any:
        value = super().clean(value)
        if value == self.empty_value or value in EMPTY_VALUES:
            return self.empty_value
        try:
            return self.coerce(value)
        except (TypeError, ValueError, ValidationError):
            raise ValidationError(
                f"Select a valid choice. {value} is not one of the available choices.",
                code="invalid_choice",
            )


class MultipleChoiceField(_ChoiceField[list[str]]):
    multi_value = True

    def parse(self, value: Any) -> list[str]:
        if not value:
            return []
        if not isinstance(value, list | tuple):
            raise ValidationError("Enter a list of values.", code="invalid_list")
        return [str(item) for item in value]

    def clean(self, value: Any) -> list[str]:
        value = self.parse(value)
        if self.required and not value:
            raise ValidationError(REQUIRED_MESSAGE, code="required")
        for item in value:
            if not self._valid_choice(item):
                raise ValidationError(
                    f"Select a valid choice. {item} is not one of the "
                    "available choices.",
                    code="invalid_choice",
                )
        return value


class DateField(Field[datetime.date]):
    def parse(self, value: Any) -> datetime.date | None:
        if value in EMPTY_VALUES:
            return None
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        try:
            parsed = parse_date(str(value).strip())
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValidationError("Enter a valid date.", code="invalid")
        return parsed


class TimeField(Field[datetime.time]):
    def parse(self, value: Any) -> datetime.time | None:
        if value in EMPTY_VALUES:
            return None
        if isinstance(value, datetime.time):
            return value
        try:
            parsed = parse_time(str(value).strip())
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValidationError("Enter a valid time.", code="invalid")
        return parsed


class DateTimeField(Field[datetime.datetime]):
    def parse(self, value: Any) -> datetime.datetime | None:
        if value in EMPTY_VALUES:
            return None
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            return datetime.datetime(value.year, value.month, value.day)
        try:
            parsed = parse_datetime(str(value).strip())
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValidationError("Enter a valid date/time.", code="invalid")
        return parsed


class DurationField(Field[datetime.timedelta]):
    def parse(self, value: Any) -> datetime.timedelta | None:
        if value in EMPTY_VALUES:
            return None
        if isinstance(value, datetime.timedelta):
            return value
        try:
            parsed = parse_duration(str(value))
        except (ValueError, OverflowError):
            raise ValidationError("Enter a valid duration.", code="invalid")
        if parsed is None:
            raise ValidationError("Enter a valid duration.", code="invalid")
        return parsed


class UUIDField(Field[uuid.UUID]):
    def parse(self, value: Any) -> uuid.UUID | None:
        if value in EMPTY_VALUES:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (AttributeError, ValueError):
            raise ValidationError("Enter a valid UUID.", code="invalid")


class JSONField(Field[Any]):
    def parse(self, value: Any) -> Any:
        if value in EMPTY_VALUES:
            return None
        if isinstance(value, list | dict | int | float):
            # Already-decoded JSON (e.g. from request.json_data).
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            raise ValidationError("Enter valid JSON.", code="invalid")


class FileField(Field[Any]):
    def __init__(
        self,
        *,
        max_length: int | None = None,
        allow_empty_file: bool = False,
        required: bool = True,
        initial: Any = None,
    ) -> None:
        super().__init__(required=required, initial=initial)
        self.max_length = max_length
        self.allow_empty_file = allow_empty_file

    def parse(self, value: Any) -> Any:
        if value in EMPTY_VALUES:
            return None
        # An uploaded file exposes `name` and `size`.
        try:
            file_name = value.name
            file_size = value.size
        except AttributeError:
            raise ValidationError("No file was submitted.", code="invalid")
        if not file_name:
            raise ValidationError("No file was submitted.", code="invalid")
        if self.max_length is not None and len(file_name) > self.max_length:
            raise ValidationError(
                f"Ensure this filename has at most {self.max_length} characters "
                f"(it has {len(file_name)}).",
                code="max_length",
            )
        if not self.allow_empty_file and not file_size:
            raise ValidationError("The submitted file is empty.", code="empty")
        return value

    def clean(self, value: Any, initial: Any = None) -> Any:
        # No new upload but an existing file — keep it.
        if not value and initial:
            return initial
        return super().clean(value)


class ImageField(FileField):
    default_validators: list[Callable[[Any], None]] = [
        validators.validate_image_file_extension
    ]

    def parse(self, value: Any) -> Any:
        uploaded = super().parse(value)
        if uploaded is None:
            return None

        from PIL import Image  # ty: ignore[unresolved-import]

        if hasattr(value, "temporary_file_path"):
            source: Any = value.temporary_file_path()
        elif hasattr(value, "read"):
            source = BytesIO(value.read())
        else:
            source = BytesIO(value["content"])

        try:
            image = Image.open(source)
            image.verify()
        except Exception as exc:
            raise ValidationError(
                "Upload a valid image. The file you uploaded was either not an "
                "image or a corrupted image.",
                code="invalid_image",
            ) from exc

        if hasattr(uploaded, "seek") and callable(uploaded.seek):
            uploaded.seek(0)
        return uploaded
