from __future__ import annotations

import datetime
from calendar import monthrange
from collections.abc import Iterator
from enum import Enum

from plain.utils import timezone


class DatetimeRangeAliases(Enum):
    TODAY = "Today"
    THIS_WEEK = "This Week"
    THIS_WEEK_TO_DATE = "This Week-to-date"
    THIS_MONTH = "This Month"
    THIS_MONTH_TO_DATE = "This Month-to-date"
    THIS_QUARTER = "This Quarter"
    THIS_QUARTER_TO_DATE = "This Quarter-to-date"
    THIS_YEAR = "This Year"
    THIS_YEAR_TO_DATE = "This Year-to-date"
    LAST_WEEK = "Last Week"
    LAST_WEEK_TO_DATE = "Last Week-to-date"
    LAST_MONTH = "Last Month"
    LAST_MONTH_TO_DATE = "Last Month-to-date"
    LAST_QUARTER = "Last Quarter"
    LAST_QUARTER_TO_DATE = "Last Quarter-to-date"
    LAST_YEAR = "Last Year"
    LAST_YEAR_TO_DATE = "Last Year-to-date"
    SINCE_30_DAYS_AGO = "Since 30 Days Ago"
    SINCE_60_DAYS_AGO = "Since 60 Days Ago"
    SINCE_90_DAYS_AGO = "Since 90 Days Ago"
    SINCE_365_DAYS_AGO = "Since 365 Days Ago"
    NEXT_WEEK = "Next Week"
    NEXT_4_WEEKS = "Next 4 Weeks"
    NEXT_MONTH = "Next Month"
    NEXT_QUARTER = "Next Quarter"
    NEXT_YEAR = "Next Year"

    # TODO doesn't include anything less than a day...
    # ex. SINCE_1_HOUR_AGO = "Since 1 Hour Ago"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_value(cls, value: str) -> DatetimeRangeAliases:
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"{value} is not a valid value for {cls.__name__}")

    @classmethod
    def to_range(cls, value: str | DatetimeRangeAliases) -> DatetimeRange:
        # Convert enum to string value if needed
        if isinstance(value, DatetimeRangeAliases):
            value = value.value

        now = timezone.localtime()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_week = start_of_today - datetime.timedelta(
            days=start_of_today.weekday()
        )
        start_of_month = start_of_today.replace(day=1)
        start_of_quarter = start_of_today.replace(
            month=((start_of_today.month - 1) // 3) * 3 + 1, day=1
        )
        start_of_year = start_of_today.replace(month=1, day=1)

        def end_of_day(dt: datetime.datetime) -> datetime.datetime:
            return dt.replace(hour=23, minute=59, second=59, microsecond=999999)

        def end_of_month(dt: datetime.datetime) -> datetime.datetime:
            last_day = monthrange(dt.year, dt.month)[1]
            return end_of_day(dt.replace(day=last_day))

        def end_of_quarter(dt: datetime.datetime) -> datetime.datetime:
            end_month = ((dt.month - 1) // 3 + 1) * 3
            return end_of_month(dt.replace(month=end_month))

        def end_of_year(dt: datetime.datetime) -> datetime.datetime:
            return end_of_month(dt.replace(month=12))

        if value == cls.TODAY.value:
            return DatetimeRange(start_of_today, end_of_day(now))
        if value == cls.THIS_WEEK.value:
            return DatetimeRange(
                start_of_week, end_of_day(start_of_week + datetime.timedelta(days=6))
            )
        if value == cls.THIS_WEEK_TO_DATE.value:
            return DatetimeRange(start_of_week, now)
        if value == cls.THIS_MONTH.value:
            return DatetimeRange(start_of_month, end_of_month(start_of_month))
        if value == cls.THIS_MONTH_TO_DATE.value:
            return DatetimeRange(start_of_month, now)
        if value == cls.THIS_QUARTER.value:
            return DatetimeRange(start_of_quarter, end_of_quarter(start_of_quarter))
        if value == cls.THIS_QUARTER_TO_DATE.value:
            return DatetimeRange(start_of_quarter, now)
        if value == cls.THIS_YEAR.value:
            return DatetimeRange(start_of_year, end_of_year(start_of_year))
        if value == cls.THIS_YEAR_TO_DATE.value:
            return DatetimeRange(start_of_year, now)
        if value == cls.LAST_WEEK.value:
            last_week_start = start_of_week - datetime.timedelta(days=7)
            return DatetimeRange(
                last_week_start,
                end_of_day(last_week_start + datetime.timedelta(days=6)),
            )
        if value == cls.LAST_WEEK_TO_DATE.value:
            return DatetimeRange(start_of_week - datetime.timedelta(days=7), now)
        if value == cls.LAST_MONTH.value:
            last_month = (start_of_month - datetime.timedelta(days=1)).replace(day=1)
            return DatetimeRange(last_month, end_of_month(last_month))
        if value == cls.LAST_MONTH_TO_DATE.value:
            last_month = (start_of_month - datetime.timedelta(days=1)).replace(day=1)
            return DatetimeRange(last_month, now)
        if value == cls.LAST_QUARTER.value:
            last_quarter = (start_of_quarter - datetime.timedelta(days=1)).replace(
                day=1
            )
            return DatetimeRange(last_quarter, end_of_quarter(last_quarter))
        if value == cls.LAST_QUARTER_TO_DATE.value:
            last_quarter = (start_of_quarter - datetime.timedelta(days=1)).replace(
                day=1
            )
            return DatetimeRange(last_quarter, now)
        if value == cls.LAST_YEAR.value:
            last_year = start_of_year.replace(year=start_of_year.year - 1)
            return DatetimeRange(last_year, end_of_year(last_year))
        if value == cls.LAST_YEAR_TO_DATE.value:
            last_year = start_of_year.replace(year=start_of_year.year - 1)
            return DatetimeRange(last_year, now)
        if value == cls.SINCE_30_DAYS_AGO.value:
            return DatetimeRange(now - datetime.timedelta(days=30), now)
        if value == cls.SINCE_60_DAYS_AGO.value:
            return DatetimeRange(now - datetime.timedelta(days=60), now)
        if value == cls.SINCE_90_DAYS_AGO.value:
            return DatetimeRange(now - datetime.timedelta(days=90), now)
        if value == cls.SINCE_365_DAYS_AGO.value:
            return DatetimeRange(now - datetime.timedelta(days=365), now)
        if value == cls.NEXT_WEEK.value:
            next_week_start = start_of_week + datetime.timedelta(days=7)
            return DatetimeRange(
                next_week_start,
                end_of_day(next_week_start + datetime.timedelta(days=6)),
            )
        if value == cls.NEXT_4_WEEKS.value:
            return DatetimeRange(now, end_of_day(now + datetime.timedelta(days=28)))
        if value == cls.NEXT_MONTH.value:
            next_month = (start_of_month + datetime.timedelta(days=31)).replace(day=1)
            return DatetimeRange(next_month, end_of_month(next_month))
        if value == cls.NEXT_QUARTER.value:
            next_quarter = (start_of_quarter + datetime.timedelta(days=90)).replace(
                day=1
            )
            return DatetimeRange(next_quarter, end_of_quarter(next_quarter))
        if value == cls.NEXT_YEAR.value:
            next_year = start_of_year.replace(year=start_of_year.year + 1)
            return DatetimeRange(next_year, end_of_year(next_year))
        raise ValueError(f"Invalid range: {value}")


class DatetimeRange:
    start: datetime.datetime
    end: datetime.datetime

    def __init__(
        self,
        start: datetime.datetime | datetime.date | str,
        end: datetime.datetime | datetime.date | str,
    ):
        # Convert all inputs to datetime.datetime
        if isinstance(start, str) and start:
            self.start = datetime.datetime.fromisoformat(start)
        elif isinstance(start, datetime.date) and not isinstance(
            start, datetime.datetime
        ):
            self.start = timezone.localtime().replace(
                year=start.year, month=start.month, day=start.day
            )
        else:
            self.start = start  # type: ignore[assignment]

        if isinstance(end, str) and end:
            self.end = datetime.datetime.fromisoformat(end)
        elif isinstance(end, datetime.date) and not isinstance(end, datetime.datetime):
            self.end = timezone.localtime().replace(
                year=end.year, month=end.month, day=end.day
            )
        else:
            self.end = end  # type: ignore[assignment]

    def as_tuple(self) -> tuple[datetime.datetime, datetime.datetime]:
        return (self.start, self.end)

    def total_days(self) -> int:
        return (self.end - self.start).days

    def iter_days(self) -> Iterator[datetime.date]:
        """Yields each day in the range (inclusive of end date)."""
        return iter(
            self.start.date() + datetime.timedelta(days=i)
            for i in range(0, self.total_days() + 1)
        )

    def iter_weeks(self) -> Iterator[datetime.datetime]:
        """Yields the start of each week in the range."""
        current = self.start - datetime.timedelta(days=self.start.weekday())
        current = current.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= self.end:
            next_week = current + datetime.timedelta(weeks=1)
            yield current
            current = next_week

    def iter_months(self) -> Iterator[datetime.datetime]:
        """Yields the start of each month in the range."""
        current = self.start.replace(day=1)
        current = current.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= self.end:
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1)
            else:
                next_month = current.replace(month=current.month + 1)
            yield current
            current = next_month

    def iter_quarters(self) -> Iterator[datetime.datetime]:
        """Yields the start of each quarter in the range."""
        current = self.start.replace(month=((self.start.month - 1) // 3) * 3 + 1, day=1)
        current = current.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= self.end:
            next_quarter_month = ((current.month - 1) // 3 + 1) * 3 + 1
            if next_quarter_month > 12:
                next_quarter_month -= 12
                next_year = current.year + 1
            else:
                next_year = current.year
            next_quarter = datetime.datetime(
                next_year, next_quarter_month, 1, tzinfo=current.tzinfo
            )
            yield current
            current = next_quarter

    def iter_years(self) -> Iterator[datetime.datetime]:
        """Yields the start of each year in the range."""
        current = self.start.replace(month=1, day=1)
        current = current.replace(hour=0, minute=0, second=0, microsecond=0)
        while current <= self.end:
            next_year = current.replace(year=current.year + 1)
            yield current
            current = next_year

    def __repr__(self) -> str:
        return f"DatetimeRange({self.start}, {self.end})"

    def __str__(self) -> str:
        return f"{self.start} to {self.end}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DatetimeRange):
            return False
        return self.start == other.start and self.end == other.end

    def __hash__(self) -> int:
        return hash((self.start, self.end))

    def __contains__(self, item: datetime.datetime) -> bool:
        return self.start <= item <= self.end
