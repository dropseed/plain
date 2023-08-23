"Commonly-used date structures"

from bolt.utils.translation import gettext_lazy as _
from bolt.utils.translation import pgettext_lazy

WEEKDAYS = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}
WEEKDAYS_ABBR = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thu",
    4: "Fri",
    5: "Sat",
    6: "Sun",
}
MONTHS = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}
MONTHS_3 = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dec",
}
MONTHS_AP = {  # month names in Associated Press style
    1: pgettext_lazy("abbrev. month", "Jan."),
    2: pgettext_lazy("abbrev. month", "Feb."),
    3: pgettext_lazy("abbrev. month", "March"),
    4: pgettext_lazy("abbrev. month", "April"),
    5: pgettext_lazy("abbrev. month", "May"),
    6: pgettext_lazy("abbrev. month", "June"),
    7: pgettext_lazy("abbrev. month", "July"),
    8: pgettext_lazy("abbrev. month", "Aug."),
    9: pgettext_lazy("abbrev. month", "Sept."),
    10: pgettext_lazy("abbrev. month", "Oct."),
    11: pgettext_lazy("abbrev. month", "Nov."),
    12: pgettext_lazy("abbrev. month", "Dec."),
}
MONTHS_ALT = {  # required for long date representation by some locales
    1: pgettext_lazy("alt. month", "January"),
    2: pgettext_lazy("alt. month", "February"),
    3: pgettext_lazy("alt. month", "March"),
    4: pgettext_lazy("alt. month", "April"),
    5: pgettext_lazy("alt. month", "May"),
    6: pgettext_lazy("alt. month", "June"),
    7: pgettext_lazy("alt. month", "July"),
    8: pgettext_lazy("alt. month", "August"),
    9: pgettext_lazy("alt. month", "September"),
    10: pgettext_lazy("alt. month", "October"),
    11: pgettext_lazy("alt. month", "November"),
    12: pgettext_lazy("alt. month", "December"),
}
