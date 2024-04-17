import datetime

_MONTH_NAMES = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_DAY_NAMES = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
    "SAT": 5,
    "SUN": 6,
}


class _ScheduleComponent:
    def __init__(self, values, raw=""):
        self.values = sorted(values)
        self._raw = raw

    def __str__(self):
        if self._raw:
            return self._raw
        return ",".join(str(v) for v in self.values)

    def __eq__(self, other):
        return self.values == other.values

    @classmethod
    def parse(cls, value, min, max, converters={}):
        if isinstance(value, int):
            if value < min or value > max:
                raise ValueError(
                    f"Schedule component should be between {min} and {max}"
                )
            return cls([value], raw=value)

        if not isinstance(value, str):
            raise ValueError("Schedule component should be an int or str")

        if value == "*":
            return cls(list(range(min, max + 1)), raw=value)

        def _convert(value):
            return converters.get(value.upper(), int(value))

        if "/" in value:
            values, step = value.split("/")
            values = cls.parse(values, min, max, converters)
            return cls([v for v in values.values if v % int(step) == 0], raw=value)

        if "-" in value:
            start, end = value.split("-")
            return cls(list(range(_convert(start), _convert(end) + 1)), raw=value)

        return cls([_convert(value)], raw=value)


class Schedule:
    def __init__(
        self,
        *,
        minute="*",
        hour="*",
        day_of_month="*",
        month="*",
        day_of_week="*",
        raw="",
    ):
        self.minute = _ScheduleComponent.parse(minute, min=0, max=59)
        self.hour = _ScheduleComponent.parse(hour, min=0, max=23)
        self.day_of_month = _ScheduleComponent.parse(day_of_month, min=1, max=31)
        self.month = _ScheduleComponent.parse(
            month,
            min=1,
            max=12,
            converters=_MONTH_NAMES,
        )
        self.day_of_week = _ScheduleComponent.parse(
            day_of_week,
            min=0,
            max=6,
            converters=_DAY_NAMES,
        )
        self._raw = raw

    def __str__(self):
        if self._raw:
            return self._raw
        return f"{self.minute} {self.hour} {self.day_of_month} {self.month} {self.day_of_week}"

    def __repr__(self) -> str:
        return f"<Schedule {self}>"

    @classmethod
    def from_cron(cls, cron):
        raw = cron

        if cron == "@yearly" or cron == "@annually":
            cron = "0 0 1 1 *"
        elif cron == "@monthly":
            cron = "0 0 1 * *"
        elif cron == "@weekly":
            cron = "0 0 * * 0"
        elif cron == "@daily" or cron == "@midnight":
            cron = "0 0 * * *"
        elif cron == "@hourly":
            cron = "0 * * * *"

        minute, hour, day_of_month, month, day_of_week = cron.split()

        return cls(
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month=month,
            day_of_week=day_of_week,
            raw=raw,
        )

    def next(self, start_at=None):
        dt = start_at or datetime.datetime.now(datetime.timezone.utc)

        # We only care about minutes, so immediately jump to the next minute
        dt += datetime.timedelta(minutes=1)
        dt = dt.replace(second=0, microsecond=0)

        def _go_to_next_day(v):
            v = v + datetime.timedelta(days=1)
            return v.replace(
                hour=self.hour.values[0],
                minute=self.minute.values[0],
            )

        # If we don't find a value in the next 500 days,
        # then the schedule is probably never going to match (i.e. Feb 31)
        max_future = dt + datetime.timedelta(days=500)

        while True:
            is_valid_day = (
                dt.month in self.month.values
                and dt.day in self.day_of_month.values
                and dt.weekday() in self.day_of_week.values
            )
            if is_valid_day:
                # We're on a valid day, now find the next valid hour and minute
                for hour in self.hour.values:
                    if hour < dt.hour:
                        continue
                    for minute in self.minute.values:
                        if hour == dt.hour and minute < dt.minute:
                            continue
                        candidate_datetime = dt.replace(hour=hour, minute=minute)
                        if candidate_datetime >= dt:
                            return candidate_datetime
                # If no valid time is found today, reset to the first valid minute and hour of the next day
                dt = _go_to_next_day(dt)
            else:
                # Increment the day until a valid month/day/weekday combination is found
                dt = _go_to_next_day(dt)

            if dt > max_future:
                raise ValueError("No valid schedule match found in the next 500 days")
