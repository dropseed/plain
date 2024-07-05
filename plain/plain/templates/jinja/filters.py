import datetime
from itertools import islice

from plain.utils.html import json_script
from plain.utils.timesince import timesince, timeuntil
from plain.utils.timezone import localtime


def localtime_filter(value, timezone=None):
    """Converts a datetime to local time in a template."""
    if not value:
        # Without this, we get the current localtime
        # which doesn't make sense as a filter
        raise ValueError("localtime filter requires a datetime")
    return localtime(value, timezone)


default_filters = {
    # The standard Python ones
    "strftime": datetime.datetime.strftime,
    "strptime": datetime.datetime.strptime,
    # To convert to user time zone
    "localtime": localtime_filter,
    "timeuntil": timeuntil,
    "timesince": timesince,
    "json_script": json_script,
    "islice": islice,  # slice for dict.items()
}
