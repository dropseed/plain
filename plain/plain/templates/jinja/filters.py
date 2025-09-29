from __future__ import annotations

import datetime
from itertools import islice
from typing import Any

from plain.utils.html import json_script
from plain.utils.timesince import timesince, timeuntil
from plain.utils.timezone import localtime


def localtime_filter(
    value: datetime.datetime | None, timezone: Any = None
) -> datetime.datetime:
    """Converts a datetime to local time in a template."""
    if not value:
        # Without this, we get the current localtime
        # which doesn't make sense as a filter
        raise ValueError("localtime filter requires a datetime")
    return localtime(value, timezone)


def pluralize_filter(value: Any, singular: str = "", plural: str = "s") -> str:
    """Returns plural suffix based on the value count.

    Usage:
        {{ count }} item{{ count|pluralize }}
        {{ count }} ox{{ count|pluralize("en") }}
        {{ count }} cact{{ count|pluralize("us","i") }}
    """
    try:
        count = int(value)
    except (ValueError, TypeError):
        return singular

    if count == 1:
        return singular

    return plural


default_filters = {
    # The standard Python ones
    "strftime": datetime.datetime.strftime,
    "strptime": datetime.datetime.strptime,
    "fromtimestamp": datetime.datetime.fromtimestamp,
    "fromisoformat": datetime.datetime.fromisoformat,
    # To convert to user time zone
    "localtime": localtime_filter,
    "timeuntil": timeuntil,
    "timesince": timesince,
    "json_script": json_script,
    "islice": islice,  # slice for dict.items()
    "pluralize": pluralize_filter,
}
