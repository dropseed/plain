import datetime
from itertools import islice

from bolt.utils.html import json_script
from bolt.utils.timesince import timesince, timeuntil
from bolt.utils.timezone import localtime


def localtime_filter(value, timezone=None):
    """Converts a datetime to local time in a template."""
    if not value:
        # Without this, we get the current localtime
        # which doesn't make sense as a filter
        return None
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
