import datetime
from enum import Enum

from plain.utils import timezone


class DatetimeRangeAliases(Enum):
    LAST_365_DAYS = "last_365_days"
    LAST_30_DAYS = "last_30_days"
    LAST_7_DAYS = "last_7_days"
    INHERIT = "inherit"

    @classmethod
    def to_range(cls, value: str) -> (datetime.datetime, datetime.datetime):
        now = timezone.localtime()
        if value == cls.LAST_365_DAYS:
            return DatetimeRange(now - datetime.timedelta(days=365), now)
        if value == cls.LAST_30_DAYS:
            return DatetimeRange(now - datetime.timedelta(days=30), now)
        if value == cls.LAST_7_DAYS:
            return DatetimeRange(now - datetime.timedelta(days=7), now)
        raise ValueError(f"Invalid range: {value}")


class DatetimeRange:
    def __init__(self, start, end):
        self.start = start
        self.end = end

        if isinstance(self.start, str) and self.start:
            self.start = datetime.datetime.fromisoformat(self.start)

        if isinstance(self.end, str) and self.end:
            self.end = datetime.datetime.fromisoformat(self.end)

        if isinstance(self.start, datetime.date):
            self.start = timezone.localtime().replace(
                year=self.start.year, month=self.start.month, day=self.start.day
            )

        if isinstance(self.end, datetime.date):
            self.end = timezone.localtime().replace(
                year=self.end.year, month=self.end.month, day=self.end.day
            )

    def as_tuple(self):
        return (self.start, self.end)

    def total_days(self):
        return (self.end - self.start).days

    def __iter__(self):
        # Iters days currently... probably should have an iter_days method instead
        return iter(
            self.start.date() + datetime.timedelta(days=i)
            for i in range(0, self.total_days())
        )

    def __repr__(self):
        return f"DatetimeRange({self.start}, {self.end})"

    def __str__(self):
        return f"{self.start} to {self.end}"

    def __eq__(self, other):
        return self.start == other.start and self.end == other.end

    def __hash__(self):
        return hash((self.start, self.end))

    def __contains__(self, item):
        return self.start <= item <= self.end
