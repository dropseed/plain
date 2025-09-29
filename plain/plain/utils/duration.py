from __future__ import annotations

import datetime


def _get_duration_components(
    duration: datetime.timedelta,
) -> tuple[int, int, int, int, int]:
    days = duration.days
    seconds = duration.seconds
    microseconds = duration.microseconds

    minutes = seconds // 60
    seconds %= 60

    hours = minutes // 60
    minutes %= 60

    return days, hours, minutes, seconds, microseconds


def duration_string(duration: datetime.timedelta) -> str:
    """Version of str(timedelta) which is not English specific."""
    days, hours, minutes, seconds, microseconds = _get_duration_components(duration)

    string = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if days:
        string = f"{days} " + string
    if microseconds:
        string += f".{microseconds:06d}"

    return string


def duration_iso_string(duration: datetime.timedelta) -> str:
    if duration < datetime.timedelta(0):
        sign = "-"
        duration *= -1
    else:
        sign = ""

    days, hours, minutes, seconds, microseconds = _get_duration_components(duration)
    ms = f".{microseconds:06d}" if microseconds else ""
    return f"{sign}P{days}DT{hours:02d}H{minutes:02d}M{seconds:02d}{ms}S"


def duration_microseconds(delta: datetime.timedelta) -> int:
    return (24 * 60 * 60 * delta.days + delta.seconds) * 1000000 + delta.microseconds
