from __future__ import annotations

import datetime
import warnings
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from plain import exceptions
from plain.preflight import PreflightResult
from plain.utils import timezone
from plain.utils.dateparse import parse_date, parse_datetime, parse_time

from .base import NOT_PROVIDED, DefaultableField

if TYPE_CHECKING:
    from plain.postgres.base import Model
    from plain.postgres.connection import DatabaseConnection


def _to_naive(value: datetime.datetime) -> datetime.datetime:
    if timezone.is_aware(value):
        value = timezone.make_naive(value, datetime.UTC)
    return value


def _get_naive_now() -> datetime.datetime:
    return _to_naive(timezone.now())


_INVALID_DATE_MESSAGE = (
    '"%(value)s" value has the correct format (YYYY-MM-DD) but it is an invalid date.'
)


class DateTimeCheckMixin(DefaultableField):
    auto_now: bool

    def preflight(self, **kwargs: Any) -> list[PreflightResult]:
        return [
            *super().preflight(**kwargs),
            *self._check_mutually_exclusive_options(),
            *self._check_fix_default_value(),
        ]

    def _check_mutually_exclusive_options(self) -> list[PreflightResult]:
        # auto_now and default are mutually exclusive options. The use of
        # both options together will trigger an Error.
        mutually_exclusive_options = [
            self.auto_now,
            self.has_default(),
        ]
        enabled_options = [
            option not in (None, False) for option in mutually_exclusive_options
        ].count(True)
        if enabled_options > 1:
            return [
                PreflightResult(
                    fix="The options auto_now and default are mutually "
                    "exclusive. Only one of these options may be present.",
                    obj=self,
                    id="fields.datetime_auto_options_mutually_exclusive",
                )
            ]
        else:
            return []

    def _check_fix_default_value(self) -> list[PreflightResult]:
        return []

    # Concrete subclasses use this in their implementations of
    # _check_fix_default_value().
    def _check_if_value_fixed(
        self,
        value: datetime.date | datetime.datetime,
        now: datetime.datetime | None = None,
    ) -> list[PreflightResult]:
        """
        Check if the given value appears to have been provided as a "fixed"
        time value, and include a warning in the returned list if it does. The
        value argument must be a date object or aware/naive datetime object. If
        now is provided, it must be a naive datetime object.
        """
        if now is None:
            now = _get_naive_now()
        offset = datetime.timedelta(seconds=10)
        lower = now - offset
        upper = now + offset
        if isinstance(value, datetime.datetime):
            value = _to_naive(value)
        else:
            assert isinstance(value, datetime.date)
            lower = lower.date()
            upper = upper.date()
        if lower <= value <= upper:
            return [
                PreflightResult(
                    fix="Fixed default value provided. "
                    "It seems you set a fixed date / time / datetime "
                    "value as default for this field. This may not be "
                    "what you want. If you want to have the current date "
                    "as default, use `plain.utils.timezone.now`",
                    obj=self,
                    id="fields.datetime_naive_default_value",
                    warning=True,
                )
            ]
        return []


class DateField(DateTimeCheckMixin, DefaultableField[datetime.date]):
    db_type_sql = "date"
    empty_strings_allowed = False

    def __init__(
        self,
        *,
        auto_now: bool = False,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        self.auto_now = auto_now
        if auto_now:
            required = False
        super().__init__(
            required=required,
            allow_null=allow_null,
            default=default,
            validators=validators,
        )

    def _check_fix_default_value(self) -> list[PreflightResult]:
        """
        Warn that using an actual date or datetime value is probably wrong;
        it's only evaluated on server startup.
        """
        if not self.has_default():
            return []

        value = self.default
        if isinstance(value, datetime.datetime):
            value = _to_naive(value).date()
        elif isinstance(value, datetime.date):
            pass
        else:
            # No explicit date / datetime value -- no checks necessary
            return []
        # At this point, value is a date object.
        return self._check_if_value_fixed(value)

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now:
            kwargs["auto_now"] = True
            del kwargs["required"]
        return name, path, args, kwargs

    def to_python(self, value: Any) -> datetime.date | None:
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            if timezone.is_aware(value):
                # Convert aware datetimes to the default time zone
                # before casting them to dates (#17742).
                default_timezone = timezone.get_default_timezone()
                value = timezone.make_naive(value, default_timezone)
            return value.date()
        if isinstance(value, datetime.date):
            return value

        try:
            parsed = parse_date(value)
            if parsed is not None:
                return parsed
        except ValueError:
            raise exceptions.ValidationError(
                _INVALID_DATE_MESSAGE,
                code="invalid_date",
                params={"value": value},
            )

        raise exceptions.ValidationError(
            '"%(value)s" value has an invalid date format. It must be in YYYY-MM-DD format.',
            code="invalid",
            params={"value": value},
        )

    def pre_save(self, model_instance: Model, add: bool) -> datetime.date | None:
        if self.auto_now:
            value = datetime.date.today()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def get_effective_default(self) -> Any:
        if not self.has_default() and self.auto_now:
            return datetime.datetime.now().date()
        return super().get_effective_default()


class DateTimeField(DateField):
    db_type_sql = "timestamp with time zone"
    empty_strings_allowed = False

    # __init__ is inherited from DateField

    def _check_fix_default_value(self) -> list[PreflightResult]:
        """
        Warn that using an actual date or datetime value is probably wrong;
        it's only evaluated on server startup.
        """
        if not self.has_default():
            return []

        value = self.default
        if isinstance(value, datetime.datetime | datetime.date):
            return self._check_if_value_fixed(value)
        # No explicit date / datetime value -- no checks necessary.
        return []

    def to_python(self, value: Any) -> datetime.datetime | None:
        if value is None:
            return value
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            value = datetime.datetime(value.year, value.month, value.day)

            # For backwards compatibility, interpret naive datetimes in
            # local time. This won't work during DST change, but we can't
            # do much about it, so we let the exceptions percolate up the
            # call stack.
            warnings.warn(
                f"DateTimeField {self.model.__name__}.{self.name} received a naive datetime "
                f"({value}) while time zone support is active.",
                RuntimeWarning,
            )
            default_timezone = timezone.get_default_timezone()
            value = timezone.make_aware(value, default_timezone)

            return value

        try:
            parsed = parse_datetime(value)
            if parsed is not None:
                return parsed
        except ValueError:
            raise exceptions.ValidationError(
                '"%(value)s" value has the correct format (YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ]) but it is an invalid date/time.',
                code="invalid_datetime",
                params={"value": value},
            )

        try:
            parsed = parse_date(value)
            if parsed is not None:
                return datetime.datetime(parsed.year, parsed.month, parsed.day)
        except ValueError:
            raise exceptions.ValidationError(
                _INVALID_DATE_MESSAGE,
                code="invalid_date",
                params={"value": value},
            )

        raise exceptions.ValidationError(
            '"%(value)s" value has an invalid format. It must be in YYYY-MM-DD HH:MM[:ss[.uuuuuu]][TZ] format.',
            code="invalid",
            params={"value": value},
        )

    def pre_save(self, model_instance: Model, add: bool) -> datetime.datetime | None:
        if self.auto_now:
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return getattr(model_instance, self.attname)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        value = self.to_python(value)
        if value is not None and timezone.is_naive(value):
            # For backwards compatibility, interpret naive datetimes in local
            # time. This won't work during DST change, but we can't do much
            # about it, so we let the exceptions percolate up the call stack.
            try:
                name = f"{self.model.__name__}.{self.name}"
            except AttributeError:
                name = "(unbound)"
            warnings.warn(
                f"DateTimeField {name} received a naive datetime ({value})"
                " while time zone support is active.",
                RuntimeWarning,
            )
            default_timezone = timezone.get_default_timezone()
            value = timezone.make_aware(value, default_timezone)
        return value

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def get_effective_default(self) -> Any:
        if not self.has_default() and self.auto_now:
            return timezone.now()
        return super().get_effective_default()


class TimeField(DateTimeCheckMixin, DefaultableField[datetime.time]):
    db_type_sql = "time without time zone"
    empty_strings_allowed = False

    def __init__(
        self,
        *,
        auto_now: bool = False,
        required: bool = True,
        allow_null: bool = False,
        default: Any = NOT_PROVIDED,
        validators: Sequence[Callable[..., Any]] = (),
    ):
        self.auto_now = auto_now
        if auto_now:
            required = False
        super().__init__(
            required=required,
            allow_null=allow_null,
            default=default,
            validators=validators,
        )

    def _check_fix_default_value(self) -> list[PreflightResult]:
        """
        Warn that using an actual date or datetime value is probably wrong;
        it's only evaluated on server startup.
        """
        if not self.has_default():
            return []

        value = self.default
        if isinstance(value, datetime.datetime):
            now = None
        elif isinstance(value, datetime.time):
            now = _get_naive_now()
            # This will not use the right date in the race condition where now
            # is just before the date change and value is just past 0:00.
            value = datetime.datetime.combine(now.date(), value)
        else:
            # No explicit time / datetime value -- no checks necessary
            return []
        # At this point, value is a datetime object.
        return self._check_if_value_fixed(value, now=now)

    def deconstruct(self) -> tuple[str | None, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        if self.auto_now is not False:
            kwargs["auto_now"] = self.auto_now
            del kwargs["required"]
        return name, path, args, kwargs

    def to_python(self, value: Any) -> datetime.time | None:
        if value is None:
            return None
        if isinstance(value, datetime.time):
            return value
        if isinstance(value, datetime.datetime):
            # Not usually a good idea to pass in a datetime here (it loses
            # information), but we'll be accommodating.
            return value.time()

        try:
            parsed = parse_time(value)
            if parsed is not None:
                return parsed
        except ValueError:
            raise exceptions.ValidationError(
                '"%(value)s" value has the correct format (HH:MM[:ss[.uuuuuu]]) but it is an invalid time.',
                code="invalid_time",
                params={"value": value},
            )

        raise exceptions.ValidationError(
            '"%(value)s" value has an invalid format. It must be in HH:MM[:ss[.uuuuuu]] format.',
            code="invalid",
            params={"value": value},
        )

    def pre_save(self, model_instance: Model, add: bool) -> datetime.time | None:
        if self.auto_now:
            value = datetime.datetime.now().time()
            setattr(model_instance, self.attname, value)
            return value
        else:
            return super().pre_save(model_instance, add)

    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        return self.to_python(value)

    def get_db_prep_value(
        self, value: Any, connection: DatabaseConnection, prepared: bool = False
    ) -> Any:
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def get_effective_default(self) -> Any:
        if not self.has_default() and self.auto_now:
            return datetime.datetime.now().time()
        return super().get_effective_default()
