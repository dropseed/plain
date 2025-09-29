"""
Timezone-related classes and functions.
"""

from __future__ import annotations

import functools
import zoneinfo
from contextlib import ContextDecorator
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from threading import local
from types import TracebackType

from plain.runtime import settings

__all__ = [
    "get_fixed_timezone",
    "get_default_timezone",
    "get_default_timezone_name",
    "get_current_timezone",
    "get_current_timezone_name",
    "activate",
    "deactivate",
    "override",
    "localtime",
    "now",
    "is_aware",
    "is_naive",
    "make_aware",
    "make_naive",
]


def get_fixed_timezone(offset: int | timedelta) -> timezone:
    """Return a tzinfo instance with a fixed offset from UTC."""
    if isinstance(offset, timedelta):
        offset = int(offset.total_seconds() // 60)
    sign = "-" if offset < 0 else "+"
    hhmm = "%02d%02d" % divmod(abs(offset), 60)  # noqa: UP031
    name = sign + hhmm
    return timezone(timedelta(minutes=offset), name)


# In order to avoid accessing settings at compile time,
# wrap the logic in a function and cache the result.
@functools.lru_cache
def get_default_timezone() -> zoneinfo.ZoneInfo:
    """
    Return the default time zone as a tzinfo instance.

    This is the time zone defined by settings.TIME_ZONE.
    """
    return zoneinfo.ZoneInfo(settings.TIME_ZONE)


# This function exists for consistency with get_current_timezone_name
def get_default_timezone_name() -> str:
    """Return the name of the default time zone."""
    return _get_timezone_name(get_default_timezone())


_active = local()


def get_current_timezone() -> tzinfo:
    """Return the currently active time zone as a tzinfo instance."""
    return getattr(_active, "value", get_default_timezone())


def get_current_timezone_name() -> str:
    """Return the name of the currently active time zone."""
    return _get_timezone_name(get_current_timezone())


def _get_timezone_name(timezone: tzinfo) -> str:
    """
    Return the offset for fixed offset timezones, or the name of timezone if
    not set.
    """
    return timezone.tzname(None) or str(timezone)


# Timezone selection functions.

# These functions don't change os.environ['TZ'] and call time.tzset()
# because it isn't thread safe.


def activate(timezone: tzinfo | str) -> None:
    """
    Set the time zone for the current thread.

    The ``timezone`` argument must be an instance of a tzinfo subclass or a
    time zone name.
    """
    if isinstance(timezone, tzinfo):
        _active.value = timezone
    elif isinstance(timezone, str):
        _active.value = zoneinfo.ZoneInfo(timezone)
    else:
        raise ValueError(f"Invalid timezone: {timezone!r}")


def deactivate() -> None:
    """
    Unset the time zone for the current thread.

    Plain will then use the time zone defined by settings.TIME_ZONE.
    """
    if hasattr(_active, "value"):
        del _active.value


class override(ContextDecorator):
    """
    Temporarily set the time zone for the current thread.

    This is a context manager that uses plain.utils.timezone.activate()
    to set the timezone on entry and restores the previously active timezone
    on exit.

    The ``timezone`` argument must be an instance of a ``tzinfo`` subclass, a
    time zone name, or ``None``. If it is ``None``, Plain enables the default
    time zone.
    """

    def __init__(self, timezone: tzinfo | str | None) -> None:
        self.timezone = timezone
        self.old_timezone: tzinfo | None = None

    def __enter__(self) -> None:
        self.old_timezone = getattr(_active, "value", None)
        if self.timezone is None:
            deactivate()
        else:
            activate(self.timezone)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.old_timezone is None:
            deactivate()
        else:
            _active.value = self.old_timezone


# Utilities


def localtime(
    value: datetime | None = None, timezone: tzinfo | None = None
) -> datetime:
    """
    Convert an aware datetime.datetime to local time.

    Only aware datetimes are allowed. When value is omitted, it defaults to
    now().

    Local time is defined by the current time zone, unless another time zone
    is specified.
    """
    if value is None:
        value = now()
    if timezone is None:
        timezone = get_current_timezone()
    # Emulate the behavior of astimezone() on Python < 3.6.
    if is_naive(value):
        raise ValueError("localtime() cannot be applied to a naive datetime")
    return value.astimezone(timezone)


def now() -> datetime:
    """
    Return a timezone aware datetime.
    """
    return datetime.now(tz=UTC)


# By design, these four functions don't perform any checks on their arguments.
# The caller should ensure that they don't receive an invalid value like None.


def is_aware(value: datetime) -> bool:
    """
    Determine if a given datetime.datetime is aware.

    The concept is defined in Python's docs:
    https://docs.python.org/library/datetime.html#datetime.tzinfo

    Assuming value.tzinfo is either None or a proper datetime.tzinfo,
    value.utcoffset() implements the appropriate logic.
    """
    return value.utcoffset() is not None


def is_naive(value: datetime) -> bool:
    """
    Determine if a given datetime.datetime is naive.

    The concept is defined in Python's docs:
    https://docs.python.org/library/datetime.html#datetime.tzinfo

    Assuming value.tzinfo is either None or a proper datetime.tzinfo,
    value.utcoffset() implements the appropriate logic.
    """
    return value.utcoffset() is None


def make_aware(value: datetime, timezone: tzinfo | None = None) -> datetime:
    """Make a naive datetime.datetime in a given time zone aware."""
    if timezone is None:
        timezone = get_current_timezone()
    # Check that we won't overwrite the timezone of an aware datetime.
    if is_aware(value):
        raise ValueError(f"make_aware expects a naive datetime, got {value}")
    # This may be wrong around DST changes!
    return value.replace(tzinfo=timezone)


def make_naive(value: datetime, timezone: tzinfo | None = None) -> datetime:
    """Make an aware datetime.datetime naive in a given time zone."""
    if timezone is None:
        timezone = get_current_timezone()
    # Emulate the behavior of astimezone() on Python < 3.6.
    if is_naive(value):
        raise ValueError("make_naive() cannot be applied to a naive datetime")
    return value.astimezone(timezone).replace(tzinfo=None)


def _datetime_ambiguous_or_imaginary(dt: datetime, tz: tzinfo) -> bool:
    return tz.utcoffset(dt.replace(fold=not dt.fold)) != tz.utcoffset(dt)
