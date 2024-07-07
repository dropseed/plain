import datetime
import subprocess

from plain.utils import timezone

from .jobs import Job, load_job

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
    def parse(cls, value, min_allowed, max_allowed, str_conversions=None):
        if str_conversions is None:
            str_conversions = {}

        if isinstance(value, int):
            if value < min_allowed or value > max_allowed:
                raise ValueError(
                    f"Schedule component should be between {min_allowed} and {max_allowed}"
                )
            return cls([value], raw=value)

        if not isinstance(value, str):
            raise ValueError("Schedule component should be an int or str")

        # First split any subcomponents and re-parse them
        if "," in value:
            return cls(
                sum(
                    (
                        cls.parse(
                            sub_value, min_allowed, max_allowed, str_conversions
                        ).values
                        for sub_value in value.split(",")
                    ),
                    [],
                ),
                raw=value,
            )

        if value == "*":
            return cls(list(range(min_allowed, max_allowed + 1)), raw=value)

        def _convert(value):
            result = str_conversions.get(value.upper(), value)
            return int(result)

        if "/" in value:
            values, step = value.split("/")
            values = cls.parse(values, min_allowed, max_allowed, str_conversions)
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
        self.minute = _ScheduleComponent.parse(minute, min_allowed=0, max_allowed=59)
        self.hour = _ScheduleComponent.parse(hour, min_allowed=0, max_allowed=23)
        self.day_of_month = _ScheduleComponent.parse(
            day_of_month, min_allowed=1, max_allowed=31
        )
        self.month = _ScheduleComponent.parse(
            month,
            min_allowed=1,
            max_allowed=12,
            str_conversions=_MONTH_NAMES,
        )
        self.day_of_week = _ScheduleComponent.parse(
            day_of_week,
            min_allowed=0,
            max_allowed=6,
            str_conversions=_DAY_NAMES,
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

    def next(self, now=None):
        """
        Find the next datetime that matches the schedule after the given datetime.
        """
        dt = now or timezone.localtime()  # Use the defined plain timezone by default

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


class ScheduledCommand(Job):
    def __init__(self, command):
        self.command = command

    def __repr__(self) -> str:
        return f"<ScheduledCommand: {self.command}>"

    def run(self):
        subprocess.run(self.command, shell=True, check=True)

    def get_unique_key(self) -> str:
        # The ScheduledCommand can be used for different commands,
        # so we need the unique_key to separate them in the scheduling uniqueness logic
        return self.command


def load_schedule(schedules):
    jobs_schedule = []

    for job, schedule in schedules:
        if isinstance(job, str):
            if job.startswith("cmd:"):
                job = ScheduledCommand(job[4:])
            else:
                job = load_job(job, {"args": [], "kwargs": {}})

        if isinstance(schedule, str):
            schedule = Schedule.from_cron(schedule)

        jobs_schedule.append((job, schedule))

    return jobs_schedule
