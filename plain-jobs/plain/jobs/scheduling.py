from __future__ import annotations

import datetime
import hashlib
import subprocess
from typing import Any

from plain.utils import timezone

from .exceptions import JobClassNotRegistered
from .jobs import Job
from .registry import jobs_registry, register_job

__all__ = ["Schedule", "ScheduledCommand"]

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
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


class _ScheduleComponent:
    def __init__(self, values: list[int], raw: str | int = "") -> None:
        self.values = sorted(values)
        self._raw = raw

    def __str__(self) -> str:
        if self._raw:
            return str(self._raw)
        return ",".join(str(v) for v in self.values)

    def __eq__(self, other: Any) -> bool:
        return self.values == other.values

    @property
    def is_wildcard(self) -> bool:
        """Whether this field contains a ``*``.

        Cron's day-of-month/day-of-week OR rule treats a field as restricted
        only when it has no ``*``, so a stepped wildcard like ``*/2`` counts as
        unrestricted here too.
        """
        return "*" in str(self._raw)

    @classmethod
    def parse(
        cls,
        value: int | str,
        min_allowed: int,
        max_allowed: int,
        str_conversions: dict[str, int] | None = None,
    ) -> _ScheduleComponent:
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

        def _convert(value: str) -> int:
            result = str_conversions.get(value.upper(), value)
            return int(result)

        def _validated(values: list[int]) -> list[int]:
            # String forms ("25", "20-30") need the same bounds check as
            # plain ints — an out-of-range value would otherwise only blow
            # up later, inside Schedule.next()'s datetime arithmetic.
            for v in values:
                if v < min_allowed or v > max_allowed:
                    raise ValueError(
                        f"Schedule component should be between {min_allowed} and {max_allowed}"
                    )
            return values

        if "/" in value:
            values, step = value.split("/")
            values = cls.parse(values, min_allowed, max_allowed, str_conversions)
            return cls([v for v in values.values if v % int(step) == 0], raw=value)

        if "-" in value:
            start, end = value.split("-")
            return cls(
                _validated(list(range(_convert(start), _convert(end) + 1))), raw=value
            )

        return cls(_validated([_convert(value)]), raw=value)


class Schedule:
    def __init__(
        self,
        *,
        minute: int | str = "*",
        hour: int | str = "*",
        day_of_month: int | str = "*",
        month: int | str = "*",
        day_of_week: int | str = "*",
        combine_days_with_or: bool = False,
        raw: str = "",
    ) -> None:
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
        # Cron numbers weekdays Sunday=0..Saturday=6 and also accepts 7 as an
        # alias for Sunday. Parse over 0..7, then fold 7 into 0 so the values
        # line up with the cron weekday computed in next().
        parsed_days = _ScheduleComponent.parse(
            day_of_week,
            min_allowed=0,
            max_allowed=7,
            str_conversions=_DAY_NAMES,
        )
        self.day_of_week = _ScheduleComponent(
            sorted({0 if value == 7 else value for value in parsed_days.values}),
            raw=day_of_week,
        )

        # Standard cron runs a job when *either* the day-of-month or the
        # day-of-week matches, but only when both fields are restricted. That
        # quirk is faithful to cron strings; the keyword API keeps the more
        # obvious AND semantics unless you opt in here.
        self.combine_days_with_or = combine_days_with_or

        self._raw = raw

    def __str__(self) -> str:
        if self._raw:
            return self._raw
        fields = f"{self.minute} {self.hour} {self.day_of_month} {self.month} {self.day_of_week}"
        if (
            self.combine_days_with_or
            and not self.day_of_month.is_wildcard
            and not self.day_of_week.is_wildcard
        ):
            # The OR day-combination matches a different set of slots, so
            # it's part of the schedule's identity (and ledger key).
            fields += " (days OR)"
        return fields

    def __repr__(self) -> str:
        return f"<Schedule {self}>"

    @classmethod
    def from_cron(cls, cron: str) -> Schedule:
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
            combine_days_with_or=True,
            raw=raw,
        )

    def next(self, now: datetime.datetime | None = None) -> datetime.datetime:
        """
        Find the next datetime that matches the schedule after the given datetime.
        """
        dt = now or timezone.localtime()  # Use the defined plain timezone by default

        # We only care about minutes, so immediately jump to the next minute
        dt += datetime.timedelta(minutes=1)
        dt = dt.replace(second=0, microsecond=0)

        def _go_to_next_day(v: datetime.datetime) -> datetime.datetime:
            v = v + datetime.timedelta(days=1)
            return v.replace(
                hour=self.hour.values[0],
                minute=self.minute.values[0],
            )

        # If we don't find a value in the next 500 days,
        # then the schedule is probably never going to match (i.e. Feb 31)
        max_future = dt + datetime.timedelta(days=500)

        # Only combine the two day fields with OR when both are restricted.
        # This doesn't depend on the candidate day, so decide it once up front.
        use_or_for_days = (
            self.combine_days_with_or
            and not self.day_of_month.is_wildcard
            and not self.day_of_week.is_wildcard
        )

        while True:
            # Cron numbers weekdays Sunday=0..Saturday=6; Python's weekday() is
            # Monday=0..Sunday=6, so shift it before comparing.
            cron_weekday = (dt.weekday() + 1) % 7
            day_of_month_matches = dt.day in self.day_of_month.values
            day_of_week_matches = cron_weekday in self.day_of_week.values

            if use_or_for_days:
                day_matches = day_of_month_matches or day_of_week_matches
            else:
                day_matches = day_of_month_matches and day_of_week_matches

            is_valid_day = dt.month in self.month.values and day_matches
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


@register_job
class ScheduledCommand(Job):
    """Run a shell command on a schedule."""

    def __init__(self, command: str) -> None:
        self.command = command

    def __repr__(self) -> str:
        return f"<ScheduledCommand: {self.command}>"

    def run(self) -> None:
        subprocess.run(self.command, shell=True, check=True)

    def default_concurrency_key(self) -> str:
        # The ScheduledCommand can be used for different commands,
        # so we need the concurrency_key to separate them for uniqueness.
        # Digest only when the raw command wouldn't fit
        # JobRequest.concurrency_key's 255-char bound once the
        # ":scheduled:<epoch>" slot stamp (21 chars) is appended — a command
        # that fits keeps its raw key, which also matches the keys
        # pre-ledger workers produced so slot dedupe holds across the
        # upgrade.
        if len(self.command) <= 234:
            return self.command
        digest = hashlib.sha256(self.command.encode()).hexdigest()[:16]
        return f"{self.command[:160]}...{digest}"


def schedule_entry_key(job: Job, schedule: Schedule) -> str:
    """
    Stable identity of a JOBS_SCHEDULE entry, used as ScheduleState.schedule_key.

    Includes the schedule itself, so changing an entry's timing starts a
    fresh ledger row (the old one becomes inert) and two entries for the
    same job with different schedules track independently.
    """
    job_class_name = jobs_registry.get_job_class_name(job.__class__)
    return f"{job_class_name}:{job.default_concurrency_key()}:{schedule}"


def schedule_entry_display(job: Job) -> str:
    """How a JOBS_SCHEDULE entry names itself — the inverse of load_schedule's
    parsing, so the `cmd:` convention lives in one module."""
    if isinstance(job, ScheduledCommand):
        return f"cmd:{job.command}"
    return jobs_registry.get_job_class_name(job.__class__)


def scheduled_concurrency_key(job: Job, slot: datetime.datetime) -> str:
    """The concurrency_key stamped on a scheduled run's rows.

    Groups a slot's request/process/result rows for queries, and its
    uniqueness under should_enqueue() dedupes against a pending row another
    process already created for the same slot (e.g. one pre-enqueued before
    the upgrade to ledger-based scheduling — the sweep migration selects
    legacy rows by this format's `:scheduled:` marker).
    """
    return f"{job.default_concurrency_key()}:scheduled:{int(slot.timestamp())}"


def load_schedule_entry(
    entry: tuple[str | Job, str | Schedule],
) -> tuple[Job, Schedule]:
    """Parse a single JOBS_SCHEDULE entry — raises if anything about it is
    wrong (shape, unregistered class, malformed schedule)."""
    job, schedule = entry

    if isinstance(job, str):
        if job.startswith("cmd:"):
            job = ScheduledCommand(job[4:])
        else:
            job = jobs_registry.load_job(job, {"args": [], "kwargs": {}})

    if isinstance(schedule, str):
        schedule = Schedule.from_cron(schedule)

    # The settings type only guarantees tuples, so validate what came out.
    if not isinstance(job, Job):
        raise ValueError(
            f"JOBS_SCHEDULE job must be a Job class path, cmd: string, or "
            f"Job instance — got {job!r}"
        )
    if not isinstance(schedule, Schedule):
        raise ValueError(
            f"JOBS_SCHEDULE schedule must be a cron string or Schedule — "
            f"got {schedule!r}"
        )

    # A Job instance whose class was never registered would enqueue rows
    # that can't be loaded at pickup.
    job_class_name = jobs_registry.get_job_class_name(job.__class__)
    if job_class_name not in jobs_registry.jobs:
        raise JobClassNotRegistered(job_class_name)

    return job, schedule


def load_schedule(
    schedules: list[tuple[str | Job, str | Schedule]],
) -> list[tuple[Job, Schedule]]:
    """Parse JOBS_SCHEDULE, failing on the first problem — the worker
    refuses to boot on broken schedule config. Consumers that want to report
    every problem (preflight) or render broken entries (admin) iterate with
    load_schedule_entry instead."""
    jobs_schedule: list[tuple[Job, Schedule]] = []
    seen_keys: set[str] = set()

    for entry in schedules:
        job, schedule = load_schedule_entry(entry)

        # Entries with the same key would share one ledger row and only one
        # of them would ever fire — refuse loudly instead.
        key = schedule_entry_key(job, schedule)
        if key in seen_keys:
            raise ValueError(
                f"Duplicate JOBS_SCHEDULE entry: {key!r}. Entries with the "
                "same job class and schedule need distinct "
                "default_concurrency_key() values to be scheduled separately."
            )
        seen_keys.add(key)

        jobs_schedule.append((job, schedule))

    return jobs_schedule
