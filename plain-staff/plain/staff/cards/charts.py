import enum
from collections import defaultdict

from plain.models import Count
from plain.models.functions import (
    TruncDate,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)
from plain.staff.dates import DatetimeRange, DatetimeRangeAliases

from .base import Card


class ChartCard(Card):
    template_name = "staff/cards/chart.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["chart_data"] = self.get_chart_data()
        return context

    def get_chart_data(self) -> dict:
        raise NotImplementedError


class TrendCard(ChartCard):
    """
    A card that renders a trend chart.
    Primarily intended for use with models, but it can also be customized.
    """

    model = None
    datetime_field = None
    datetime_range = DatetimeRangeAliases.SINCE_30_DAYS_AGO

    class Buckets(enum.Enum):
        DAY = "day"
        WEEK = "week"
        MONTH = "month"
        QUARTER = "quarter"
        YEAR = "year"

    bucket_by = Buckets.DAY

    def get_description(self) -> str:
        return self.datetime_range.value

    def get_trend_datetime_range(self) -> DatetimeRange:
        return DatetimeRangeAliases.to_range(self.datetime_range)

    def get_trend_data(self) -> list[int | float]:
        if not self.model or not self.datetime_field:
            raise NotImplementedError(
                "model and datetime_field must be set, or get_values must be overridden"
            )

        datetime_range = self.get_trend_datetime_range()

        filter_kwargs = {f"{self.datetime_field}__range": datetime_range.as_tuple()}

        truncator = {
            self.Buckets.DAY: TruncDate,
            self.Buckets.WEEK: TruncWeek,
            self.Buckets.MONTH: TruncMonth,
            self.Buckets.QUARTER: TruncQuarter,
            self.Buckets.YEAR: TruncYear,
        }[self.bucket_by]

        counts_by_date = (
            self.model.objects.filter(**filter_kwargs)
            .annotate(chart_date=truncator(self.datetime_field))
            .values("chart_date")
            .annotate(chart_date_count=Count("id"))
        )

        # Will do the zero filling for us on key access
        date_values = defaultdict(int)

        for row in counts_by_date:
            date_values[row["chart_date"]] = row["chart_date_count"]

        # Now get the filled data for our date range
        iterator = {
            self.Buckets.DAY: datetime_range.iter_days,
            self.Buckets.WEEK: datetime_range.iter_weeks,
            self.Buckets.MONTH: datetime_range.iter_months,
            self.Buckets.QUARTER: datetime_range.iter_quarters,
            self.Buckets.YEAR: datetime_range.iter_years,
        }[self.bucket_by]
        return [date_values[date] for date in iterator()]

    def get_trend_labels(self) -> list[str]:
        datetime_range = self.get_trend_datetime_range()
        iterator = {
            self.Buckets.DAY: datetime_range.iter_days,
            self.Buckets.WEEK: datetime_range.iter_weeks,
            self.Buckets.MONTH: datetime_range.iter_months,
            self.Buckets.QUARTER: datetime_range.iter_quarters,
            self.Buckets.YEAR: datetime_range.iter_years,
        }[self.bucket_by]
        return [date.strftime("%Y-%m-%d") for date in iterator()]

    def get_chart_data(self) -> dict:
        trend_labels = self.get_trend_labels()
        trend_data = self.get_trend_data()

        return {
            "type": "bar",
            "data": {
                "labels": trend_labels,
                "datasets": [
                    {
                        "data": trend_data,
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
                        "suggestedMin": 0,
                    },
                },
                "maintainAspectRatio": False,
                "elements": {
                    "bar": {"borderRadius": "3", "backgroundColor": "rgb(28, 25, 23)"}
                },
            },
        }
