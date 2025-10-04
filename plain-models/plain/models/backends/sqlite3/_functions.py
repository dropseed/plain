"""
Implementations of SQL functions for SQLite.
"""

from __future__ import annotations

import functools
import random
import statistics
import zoneinfo
from datetime import date, datetime, time, timedelta
from hashlib import md5, sha1, sha224, sha256, sha384, sha512
from math import (
    acos,
    asin,
    atan,
    atan2,
    ceil,
    cos,
    degrees,
    exp,
    floor,
    fmod,
    log,
    pi,
    radians,
    sin,
    sqrt,
    tan,
)
from re import search as re_search
from typing import TYPE_CHECKING, Any

from plain.models.backends.utils import (
    split_tzname_delta,
    typecast_time,
    typecast_timestamp,
)
from plain.utils import timezone
from plain.utils.duration import duration_microseconds

if TYPE_CHECKING:
    from plain.models.backends.sqlite3.base import SQLiteDatabaseWrapper


def register(connection: SQLiteDatabaseWrapper) -> None:
    create_deterministic_function = functools.partial(
        connection.create_function,  # type: ignore[attr-defined]
        deterministic=True,
    )
    create_deterministic_function("plain_date_extract", 2, _sqlite_datetime_extract)
    create_deterministic_function("plain_date_trunc", 4, _sqlite_date_trunc)
    create_deterministic_function(
        "plain_datetime_cast_date", 3, _sqlite_datetime_cast_date
    )
    create_deterministic_function(
        "plain_datetime_cast_time", 3, _sqlite_datetime_cast_time
    )
    create_deterministic_function("plain_datetime_extract", 4, _sqlite_datetime_extract)
    create_deterministic_function("plain_datetime_trunc", 4, _sqlite_datetime_trunc)
    create_deterministic_function("plain_time_extract", 2, _sqlite_time_extract)
    create_deterministic_function("plain_time_trunc", 4, _sqlite_time_trunc)
    create_deterministic_function("plain_time_diff", 2, _sqlite_time_diff)
    create_deterministic_function("plain_timestamp_diff", 2, _sqlite_timestamp_diff)
    create_deterministic_function("plain_format_dtdelta", 3, _sqlite_format_dtdelta)
    create_deterministic_function("regexp", 2, _sqlite_regexp)
    create_deterministic_function("BITXOR", 2, _sqlite_bitxor)
    create_deterministic_function("COT", 1, _sqlite_cot)
    create_deterministic_function("LPAD", 3, _sqlite_lpad)
    create_deterministic_function("MD5", 1, _sqlite_md5)
    create_deterministic_function("REPEAT", 2, _sqlite_repeat)
    create_deterministic_function("REVERSE", 1, _sqlite_reverse)
    create_deterministic_function("RPAD", 3, _sqlite_rpad)
    create_deterministic_function("SHA1", 1, _sqlite_sha1)
    create_deterministic_function("SHA224", 1, _sqlite_sha224)
    create_deterministic_function("SHA256", 1, _sqlite_sha256)
    create_deterministic_function("SHA384", 1, _sqlite_sha384)
    create_deterministic_function("SHA512", 1, _sqlite_sha512)
    create_deterministic_function("SIGN", 1, _sqlite_sign)
    # Don't use the built-in RANDOM() function because it returns a value
    # in the range [-1 * 2^63, 2^63 - 1] instead of [0, 1).
    connection.create_function("RAND", 0, random.random)  # type: ignore[attr-defined]
    connection.create_aggregate("STDDEV_POP", 1, StdDevPop)  # type: ignore[attr-defined]
    connection.create_aggregate("STDDEV_SAMP", 1, StdDevSamp)  # type: ignore[attr-defined]
    connection.create_aggregate("VAR_POP", 1, VarPop)  # type: ignore[attr-defined]
    connection.create_aggregate("VAR_SAMP", 1, VarSamp)  # type: ignore[attr-defined]
    # Some math functions are enabled by default in SQLite 3.35+.
    sql = "select sqlite_compileoption_used('ENABLE_MATH_FUNCTIONS')"
    if not connection.execute(sql).fetchone()[0]:  # type: ignore[union-attr]
        create_deterministic_function("ACOS", 1, _sqlite_acos)
        create_deterministic_function("ASIN", 1, _sqlite_asin)
        create_deterministic_function("ATAN", 1, _sqlite_atan)
        create_deterministic_function("ATAN2", 2, _sqlite_atan2)
        create_deterministic_function("CEILING", 1, _sqlite_ceiling)
        create_deterministic_function("COS", 1, _sqlite_cos)
        create_deterministic_function("DEGREES", 1, _sqlite_degrees)
        create_deterministic_function("EXP", 1, _sqlite_exp)
        create_deterministic_function("FLOOR", 1, _sqlite_floor)
        create_deterministic_function("LN", 1, _sqlite_ln)
        create_deterministic_function("LOG", 2, _sqlite_log)
        create_deterministic_function("MOD", 2, _sqlite_mod)
        create_deterministic_function("PI", 0, _sqlite_pi)
        create_deterministic_function("POWER", 2, _sqlite_power)
        create_deterministic_function("RADIANS", 1, _sqlite_radians)
        create_deterministic_function("SIN", 1, _sqlite_sin)
        create_deterministic_function("SQRT", 1, _sqlite_sqrt)
        create_deterministic_function("TAN", 1, _sqlite_tan)


def _sqlite_datetime_parse(
    dt: str | None, tzname: str | None = None, conn_tzname: str | None = None
) -> date | datetime | None:
    if dt is None:
        return None
    try:
        parsed_dt: date | datetime | None = typecast_timestamp(dt)
    except (TypeError, ValueError):
        return None
    if conn_tzname:
        parsed_dt = parsed_dt.replace(tzinfo=zoneinfo.ZoneInfo(conn_tzname))  # type: ignore[union-attr]
    if tzname is not None and tzname != conn_tzname:
        tzname, sign, offset = split_tzname_delta(tzname)
        if offset:
            hours, minutes = offset.split(":")
            offset_delta = timedelta(hours=int(hours), minutes=int(minutes))
            parsed_dt += offset_delta if sign == "+" else -offset_delta  # type: ignore[assignment,operator]
        parsed_dt = timezone.localtime(parsed_dt, zoneinfo.ZoneInfo(tzname))  # type: ignore[arg-type]
    return parsed_dt


def _sqlite_date_trunc(
    lookup_type: str, dt: str | None, tzname: str | None, conn_tzname: str | None
) -> str | None:
    parsed_dt = _sqlite_datetime_parse(dt, tzname, conn_tzname)
    if parsed_dt is None:
        return None
    if lookup_type == "year":
        return f"{parsed_dt.year:04d}-01-01"
    elif lookup_type == "quarter":
        month_in_quarter = parsed_dt.month - (parsed_dt.month - 1) % 3
        return f"{parsed_dt.year:04d}-{month_in_quarter:02d}-01"
    elif lookup_type == "month":
        return f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-01"
    elif lookup_type == "week":
        parsed_dt -= timedelta(days=parsed_dt.weekday())  # type: ignore[operator]
        return f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d}"
    elif lookup_type == "day":
        return f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d}"
    raise ValueError(f"Unsupported lookup type: {lookup_type!r}")


def _sqlite_time_trunc(
    lookup_type: str, dt: str | None, tzname: str | None, conn_tzname: str | None
) -> str | None:
    if dt is None:
        return None
    dt_parsed = _sqlite_datetime_parse(dt, tzname, conn_tzname)
    result: date | datetime | time | None
    if dt_parsed is None:
        try:
            result = typecast_time(dt)
        except (ValueError, TypeError):
            return None
    else:
        result = dt_parsed
    if lookup_type == "hour":
        return f"{result.hour:02d}:00:00"  # type: ignore[union-attr]
    elif lookup_type == "minute":
        return f"{result.hour:02d}:{result.minute:02d}:00"  # type: ignore[union-attr]
    elif lookup_type == "second":
        return f"{result.hour:02d}:{result.minute:02d}:{result.second:02d}"  # type: ignore[union-attr]
    raise ValueError(f"Unsupported lookup type: {lookup_type!r}")


def _sqlite_datetime_cast_date(
    dt: str | None, tzname: str | None, conn_tzname: str | None
) -> str | None:
    parsed_dt = _sqlite_datetime_parse(dt, tzname, conn_tzname)
    if parsed_dt is None:
        return None
    return parsed_dt.date().isoformat()  # type: ignore[union-attr]


def _sqlite_datetime_cast_time(
    dt: str | None, tzname: str | None, conn_tzname: str | None
) -> str | None:
    parsed_dt = _sqlite_datetime_parse(dt, tzname, conn_tzname)
    if parsed_dt is None:
        return None
    return parsed_dt.time().isoformat()  # type: ignore[union-attr]


def _sqlite_datetime_extract(
    lookup_type: str,
    dt: str | None,
    tzname: str | None = None,
    conn_tzname: str | None = None,
) -> int | None:
    parsed_dt = _sqlite_datetime_parse(dt, tzname, conn_tzname)
    if parsed_dt is None:
        return None
    if lookup_type == "week_day":
        return (parsed_dt.isoweekday() % 7) + 1  # type: ignore[union-attr]
    elif lookup_type == "iso_week_day":
        return parsed_dt.isoweekday()  # type: ignore[union-attr]
    elif lookup_type == "week":
        return parsed_dt.isocalendar().week  # type: ignore[union-attr]
    elif lookup_type == "quarter":
        return ceil(parsed_dt.month / 3)
    elif lookup_type == "iso_year":
        return parsed_dt.isocalendar().year  # type: ignore[union-attr]
    else:
        return getattr(parsed_dt, lookup_type)


def _sqlite_datetime_trunc(
    lookup_type: str, dt: str | None, tzname: str | None, conn_tzname: str | None
) -> str | None:
    parsed_dt = _sqlite_datetime_parse(dt, tzname, conn_tzname)
    if parsed_dt is None:
        return None
    if lookup_type == "year":
        return f"{parsed_dt.year:04d}-01-01 00:00:00"
    elif lookup_type == "quarter":
        month_in_quarter = parsed_dt.month - (parsed_dt.month - 1) % 3
        return f"{parsed_dt.year:04d}-{month_in_quarter:02d}-01 00:00:00"
    elif lookup_type == "month":
        return f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-01 00:00:00"
    elif lookup_type == "week":
        parsed_dt -= timedelta(days=parsed_dt.weekday())  # type: ignore[operator]
        return (
            f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d} 00:00:00"
        )
    elif lookup_type == "day":
        return (
            f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d} 00:00:00"
        )
    elif lookup_type == "hour":
        return f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d} {parsed_dt.hour:02d}:00:00"  # type: ignore[union-attr]
    elif lookup_type == "minute":
        return (
            f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d} "
            f"{parsed_dt.hour:02d}:{parsed_dt.minute:02d}:00"  # type: ignore[union-attr]
        )
    elif lookup_type == "second":
        return (
            f"{parsed_dt.year:04d}-{parsed_dt.month:02d}-{parsed_dt.day:02d} "
            f"{parsed_dt.hour:02d}:{parsed_dt.minute:02d}:{parsed_dt.second:02d}"  # type: ignore[union-attr]
        )
    raise ValueError(f"Unsupported lookup type: {lookup_type!r}")


def _sqlite_time_extract(lookup_type: str, dt: str | None) -> int | None:
    if dt is None:
        return None
    try:
        parsed_time = typecast_time(dt)
    except (ValueError, TypeError):
        return None
    return getattr(parsed_time, lookup_type)  # type: ignore[union-attr]


def _sqlite_prepare_dtdelta_param(
    conn: str, param: Any
) -> timedelta | date | datetime | Any:
    if conn in ["+", "-"]:
        if isinstance(param, int):
            return timedelta(0, 0, param)
        else:
            return typecast_timestamp(param)
    return param


def _sqlite_format_dtdelta(
    connector: str | None, lhs: Any, rhs: Any
) -> str | int | float | None:
    """
    LHS and RHS can be either:
    - An integer number of microseconds
    - A string representing a datetime
    - A scalar value, e.g. float
    """
    if connector is None or lhs is None or rhs is None:
        return None
    connector = connector.strip()
    try:
        real_lhs = _sqlite_prepare_dtdelta_param(connector, lhs)
        real_rhs = _sqlite_prepare_dtdelta_param(connector, rhs)
    except (ValueError, TypeError):
        return None
    if connector == "+":
        # typecast_timestamp() returns a date or a datetime without timezone.
        # It will be formatted as "%Y-%m-%d" or "%Y-%m-%d %H:%M:%S[.%f]"
        out = str(real_lhs + real_rhs)  # type: ignore[operator]
    elif connector == "-":
        out = str(real_lhs - real_rhs)  # type: ignore[operator]
    elif connector == "*":
        out = real_lhs * real_rhs  # type: ignore[operator]
    else:
        out = real_lhs / real_rhs  # type: ignore[operator]
    return out


def _sqlite_time_diff(lhs: str | None, rhs: str | None) -> int | None:
    if lhs is None or rhs is None:
        return None
    left = typecast_time(lhs)
    right = typecast_time(rhs)
    return (
        (left.hour * 60 * 60 * 1000000)  # type: ignore[union-attr]
        + (left.minute * 60 * 1000000)  # type: ignore[union-attr]
        + (left.second * 1000000)  # type: ignore[union-attr]
        + (left.microsecond)  # type: ignore[union-attr]
        - (right.hour * 60 * 60 * 1000000)  # type: ignore[union-attr]
        - (right.minute * 60 * 1000000)  # type: ignore[union-attr]
        - (right.second * 1000000)  # type: ignore[union-attr]
        - (right.microsecond)  # type: ignore[union-attr]
    )


def _sqlite_timestamp_diff(lhs: str | None, rhs: str | None) -> int | None:
    if lhs is None or rhs is None:
        return None
    left = typecast_timestamp(lhs)
    right = typecast_timestamp(rhs)
    return duration_microseconds(left - right)  # type: ignore[arg-type,operator]


def _sqlite_regexp(pattern: str | None, string: Any) -> bool | None:
    if pattern is None or string is None:
        return None
    if not isinstance(string, str):
        string = str(string)
    return bool(re_search(pattern, string))


def _sqlite_acos(x: float | None) -> float | None:
    if x is None:
        return None
    return acos(x)


def _sqlite_asin(x: float | None) -> float | None:
    if x is None:
        return None
    return asin(x)


def _sqlite_atan(x: float | None) -> float | None:
    if x is None:
        return None
    return atan(x)


def _sqlite_atan2(y: float | None, x: float | None) -> float | None:
    if y is None or x is None:
        return None
    return atan2(y, x)


def _sqlite_bitxor(x: int | None, y: int | None) -> int | None:
    if x is None or y is None:
        return None
    return x ^ y


def _sqlite_ceiling(x: float | None) -> float | None:
    if x is None:
        return None
    return ceil(x)


def _sqlite_cos(x: float | None) -> float | None:
    if x is None:
        return None
    return cos(x)


def _sqlite_cot(x: float | None) -> float | None:
    if x is None:
        return None
    return 1 / tan(x)


def _sqlite_degrees(x: float | None) -> float | None:
    if x is None:
        return None
    return degrees(x)


def _sqlite_exp(x: float | None) -> float | None:
    if x is None:
        return None
    return exp(x)


def _sqlite_floor(x: float | None) -> float | None:
    if x is None:
        return None
    return floor(x)


def _sqlite_ln(x: float | None) -> float | None:
    if x is None:
        return None
    return log(x)


def _sqlite_log(base: float | None, x: float | None) -> float | None:
    if base is None or x is None:
        return None
    # Arguments reversed to match SQL standard.
    return log(x, base)


def _sqlite_lpad(
    text: str | None, length: int | None, fill_text: str | None
) -> str | None:
    if text is None or length is None or fill_text is None:
        return None
    delta = length - len(text)
    if delta <= 0:
        return text[:length]
    return (fill_text * length)[:delta] + text


def _sqlite_md5(text: str | None) -> str | None:
    if text is None:
        return None
    return md5(text.encode()).hexdigest()


def _sqlite_mod(x: float | None, y: float | None) -> float | None:
    if x is None or y is None:
        return None
    return fmod(x, y)


def _sqlite_pi() -> float:
    return pi


def _sqlite_power(x: float | None, y: float | None) -> float | None:
    if x is None or y is None:
        return None
    return x**y


def _sqlite_radians(x: float | None) -> float | None:
    if x is None:
        return None
    return radians(x)


def _sqlite_repeat(text: str | None, count: int | None) -> str | None:
    if text is None or count is None:
        return None
    return text * count


def _sqlite_reverse(text: str | None) -> str | None:
    if text is None:
        return None
    return text[::-1]


def _sqlite_rpad(
    text: str | None, length: int | None, fill_text: str | None
) -> str | None:
    if text is None or length is None or fill_text is None:
        return None
    return (text + fill_text * length)[:length]


def _sqlite_sha1(text: str | None) -> str | None:
    if text is None:
        return None
    return sha1(text.encode()).hexdigest()


def _sqlite_sha224(text: str | None) -> str | None:
    if text is None:
        return None
    return sha224(text.encode()).hexdigest()


def _sqlite_sha256(text: str | None) -> str | None:
    if text is None:
        return None
    return sha256(text.encode()).hexdigest()


def _sqlite_sha384(text: str | None) -> str | None:
    if text is None:
        return None
    return sha384(text.encode()).hexdigest()


def _sqlite_sha512(text: str | None) -> str | None:
    if text is None:
        return None
    return sha512(text.encode()).hexdigest()


def _sqlite_sign(x: float | None) -> int | None:
    if x is None:
        return None
    return (x > 0) - (x < 0)


def _sqlite_sin(x: float | None) -> float | None:
    if x is None:
        return None
    return sin(x)


def _sqlite_sqrt(x: float | None) -> float | None:
    if x is None:
        return None
    return sqrt(x)


def _sqlite_tan(x: float | None) -> float | None:
    if x is None:
        return None
    return tan(x)


class ListAggregate(list):
    step = list.append


class StdDevPop(ListAggregate):
    finalize = statistics.pstdev


class StdDevSamp(ListAggregate):
    finalize = statistics.stdev


class VarPop(ListAggregate):
    finalize = statistics.pvariance


class VarSamp(ListAggregate):
    finalize = statistics.variance
