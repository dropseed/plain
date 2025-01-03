import datetime

from plain.utils.html import avoid_wrapping
from plain.utils.text import pluralize_lazy
from plain.utils.timezone import is_aware


def timesince(
    d: datetime.datetime,
    *,
    now: datetime.datetime | None = None,
    reversed: bool = False,
    format: str | dict[str, str] = "verbose",
    depth: int = 2,
) -> str:
    """
    Take two datetime objects and return the time between d and now as a nicely
    formatted string, e.g., "10 minutes" or "10m" (depending on the format).

    `format` can be:
        - "verbose": e.g., "1 year, 2 months"
        - "short": e.g., "1y 2m"
        - A custom dictionary defining time unit formats.

    Units used are years, months, weeks, days, hours, and minutes.
    Seconds and microseconds are ignored.

    The algorithm takes into account the varying duration of years and months.
    For example, there is exactly "1 year, 1 month" between 2013/02/10 and
    2014/03/10, but also between 2007/08/10 and 2008/09/10 despite the delta
    being 393 days in the former case and 397 in the latter.

    Up to `depth` adjacent units will be displayed. For example,
    "2 weeks, 3 days" and "1 year, 3 months" are possible outputs, but
    "2 weeks, 3 hours" and "1 year, 5 days" are not.

    Arguments:
        d: A datetime object representing the starting time.
        now: A datetime object representing the current time. Defaults to the
             current time if not provided.
        reversed: If True, calculates time until `d` rather than since `d`.
        format: The output format, either "verbose", "short", or a custom
                dictionary of time unit formats.
        depth: An integer specifying the number of adjacent time units to display.

    Returns:
        A string representing the time difference, formatted according to the
        specified format.

    Raises:
        ValueError: If depth is less than 1 or if format is invalid.
    """
    TIME_CHUNKS = [
        60 * 60 * 24 * 7,  # week
        60 * 60 * 24,  # day
        60 * 60,  # hour
        60,  # minute
    ]
    MONTHS_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    TIME_STRINGS_KEYS = ["year", "month", "week", "day", "hour", "minute"]

    VERBOSE_TIME_STRINGS = {
        "year": pluralize_lazy("%(num)d year", "%(num)d years", "num"),
        "month": pluralize_lazy("%(num)d month", "%(num)d months", "num"),
        "week": pluralize_lazy("%(num)d week", "%(num)d weeks", "num"),
        "day": pluralize_lazy("%(num)d day", "%(num)d days", "num"),
        "hour": pluralize_lazy("%(num)d hour", "%(num)d hours", "num"),
        "minute": pluralize_lazy("%(num)d minute", "%(num)d minutes", "num"),
    }
    SHORT_TIME_STRINGS = {
        "year": "%(num)dy",
        "month": "%(num)dmo",
        "week": "%(num)dw",
        "day": "%(num)dd",
        "hour": "%(num)dh",
        "minute": "%(num)dm",
    }

    # Determine time_strings based on format
    if format == "verbose":
        time_strings = VERBOSE_TIME_STRINGS
    elif format == "short":
        time_strings = SHORT_TIME_STRINGS
    elif isinstance(format, dict):
        time_strings = format
    else:
        raise ValueError(
            "format must be 'verbose', 'short', or a custom dictionary of formats."
        )

    if depth <= 0:
        raise ValueError("depth must be greater than 0.")

    # Convert datetime.date to datetime.datetime for comparison.
    if not isinstance(d, datetime.datetime):
        d = datetime.datetime(d.year, d.month, d.day)
    if now and not isinstance(now, datetime.datetime):
        now = datetime.datetime(now.year, now.month, now.day)

    now = now or datetime.datetime.now(datetime.UTC if is_aware(d) else None)

    if reversed:
        d, now = now, d
    delta = now - d

    # Ignore microseconds.
    since = delta.days * 24 * 60 * 60 + delta.seconds
    if since <= 0:
        # d is in the future compared to now, stop processing.
        return avoid_wrapping(time_strings["minute"] % {"num": 0})

    # Get years and months.
    total_months = (now.year - d.year) * 12 + (now.month - d.month)
    if d.day > now.day or (d.day == now.day and d.time() > now.time()):
        total_months -= 1
    years, months = divmod(total_months, 12)

    # Calculate the remaining time.
    if years or months:
        pivot_year = d.year + years
        pivot_month = d.month + months
        if pivot_month > 12:
            pivot_month -= 12
            pivot_year += 1
        pivot = datetime.datetime(
            pivot_year,
            pivot_month,
            min(MONTHS_DAYS[pivot_month - 1], d.day),
            d.hour,
            d.minute,
            d.second,
            tzinfo=d.tzinfo,
        )
    else:
        pivot = d
    remaining_time = (now - pivot).total_seconds()
    partials = [years, months]
    for chunk in TIME_CHUNKS:
        count = int(remaining_time // chunk)
        partials.append(count)
        remaining_time -= chunk * count

    # Find the first non-zero part (if any) and then build the result, until
    # depth.
    i = 0
    for i, value in enumerate(partials):
        if value != 0:
            break
    else:
        return avoid_wrapping(time_strings["minute"] % {"num": 0})

    result = []
    current_depth = 0
    while i < len(TIME_STRINGS_KEYS) and current_depth < depth:
        value = partials[i]
        if value == 0:
            break
        name = TIME_STRINGS_KEYS[i]
        result.append(avoid_wrapping(time_strings[name] % {"num": value}))
        current_depth += 1
        i += 1

    return ", ".join(result)


def timeuntil(
    d: datetime.datetime,
    now: datetime.datetime | None = None,
    format: str | dict[str, str] = "verbose",
    depth: int = 2,
) -> str:
    """
    Like timesince, but return a string measuring the time until the given time.
    """
    return timesince(d, now=now, reversed=True, format=format, depth=depth)
