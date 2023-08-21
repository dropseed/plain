from itertools import islice
from django.utils.timesince import timeuntil, timesince
from django.utils.formats import date_format, time_format
from jinja2.utils import htmlsafe_json_dumps
from django.utils.timezone import localtime
import datetime
from django.utils.html import format_html


def json_script(value, id):
    return format_html(
        '<script type="application/json" id="{}">{}</script>',
        id,
        htmlsafe_json_dumps(value),
    )


default_filters = {
    # The standard Python ones
    "strftime": datetime.datetime.strftime,
    "isoformat": datetime.datetime.isoformat,
    # To convert to user time zone
    "localtime": localtime,
    # Django's...
    "date": date_format,
    "time": time_format,
    "timeuntil": timeuntil,
    "timesince": timesince,
    "json_script": json_script,
    "islice": islice,  # slice for dict.items()
}
