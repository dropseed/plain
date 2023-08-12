import datetime
from datetime import timedelta
from enum import Enum

from django.utils import timezone
from django.utils.functional import cached_property

from .base import BaseAdminView


class AdminCardView(BaseAdminView):
    class Sizes(Enum):
        # Three column grid
        SM = 1
        MD = 2
        LG = 3
        XL = 3

    template_name = "bolt/admin/card.html"
    size: Sizes = Sizes.MD
    # unique_id: str  # Use for tying to dashboards, require it

    @classmethod
    def view_name(cls) -> str:
        return f"card_{cls.get_slug()}"


class AdminTextCardView(AdminCardView):
    text: str = ""
    template_name = "bolt/admin/cards/text.html"

    def get_context(self):
        context = super().get_context()
        context["text"] = self.get_text()
        return context

    def get_text(self) -> str:
        return self.text


class AdminChartCardView(AdminCardView):
    template_name = "bolt/admin/cards/chart.html"

    def get_context(self):
        context = super().get_context()
        context["chart_data"] = self.get_chart_data()
        return context

    def get_chart_data(self) -> dict:
        raise NotImplementedError


class DateRange:
    def __init__(self, start, end):
        self.start = start
        self.end = end

        if isinstance(self.start, datetime.datetime):
            self.start = self.start.date()

        if isinstance(self.end, datetime.datetime):
            self.end = self.end.date()

    def days(self):
        return (self.end - self.start).days

    def __iter__(self):
        return iter(self.start + timedelta(days=i) for i in range(0, self.days()))

    def __repr__(self):
        return f"DateRange({self.start}, {self.end})"

    def __str__(self):
        return f"{self.start} - {self.end}"

    def __eq__(self, other):
        return self.start == other.start and self.end == other.end

    def __hash__(self):
        return hash((self.start, self.end))

    def __contains__(self, item):
        return self.start <= item <= self.end


class AdminTrendCardView(AdminChartCardView):
    class Ranges(Enum):
        LAST_365_DAYS = "last_365_days"
        LAST_30_DAYS = "last_30_days"
        LAST_7_DAYS = "last_7_days"

    range: Ranges = Ranges.LAST_30_DAYS

    @cached_property
    def date_range(self) -> DateRange:
        return self.get_date_range()

    def get_date_range(self) -> DateRange:
        now = timezone.now()

        if self.range == self.Ranges.LAST_365_DAYS:
            return DateRange(now - timedelta(days=365), now)

        if self.range == self.Ranges.LAST_30_DAYS:
            return DateRange(now - timedelta(days=30), now)

        if self.range == self.Ranges.LAST_7_DAYS:
            return DateRange(now - timedelta(days=7), now)

        raise ValueError(f"Invalid range: {self.range}")

    def get_values(self) -> dict[datetime.date, int]:
        raise NotImplementedError

    def get_chart_data(self) -> dict:
        date_labels = [date.strftime("%Y-%m-%d") for date in self.date_range]
        date_values = self.get_values()

        for date in self.date_range:
            if date not in date_values:
                date_values[date] = 0

        # Sort the date values
        data = [date_values[date] for date in sorted(date_values.keys())]

        return {
            "type": "bar",
            "data": {
                "labels": date_labels,
                "datasets": [
                    {
                        "data": data,
                    }
                ],
            },
            # Hide the label
            # "options": {"legend": {"display": False}},
            # Hide the scales
            "options": {
                "plugins": {"legend": {"display": False}},
                "scales": {
                    "x": {
                        "display": False,
                    },
                    "y": {
                        "display": False,
                    },
                },
            },
        }
