import datetime
from itertools import islice

from bolt.utils.html import json_script
from bolt.utils.timesince import timesince, timeuntil
from bolt.utils.timezone import localtime

default_filters = {
    # The standard Python ones
    "strftime": datetime.datetime.strftime,
    "strptime": datetime.datetime.strptime,
    # To convert to user time zone
    "localtime": localtime,
    "timeuntil": timeuntil,
    "timesince": timesince,
    "json_script": json_script,
    "islice": islice,  # slice for dict.items()
}
