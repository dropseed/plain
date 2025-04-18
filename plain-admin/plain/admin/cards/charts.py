from collections import defaultdict

from plain.admin.dates import DatetimeRangeAliases
from plain.models import Count
from plain.models.functions import (
    TruncDate,
    TruncMonth,
)

from .base import Card


class ChartCard(Card):
    template_name = "admin/cards/chart.html"

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
    default_display = DatetimeRangeAliases.SINCE_30_DAYS_AGO

    displays = DatetimeRangeAliases

    def get_description(self):
        datetime_range = DatetimeRangeAliases.to_range(self.get_current_display())
        return f"{datetime_range.start} to {datetime_range.end}"

    def get_current_display(self):
        if s := super().get_current_display():
            return DatetimeRangeAliases.from_value(s)
        return self.default_display

    def get_trend_data(self) -> list[int | float]:
        if not self.model or not self.datetime_field:
            raise NotImplementedError(
                "model and datetime_field must be set, or get_values must be overridden"
            )

        datetime_range = DatetimeRangeAliases.to_range(self.get_current_display())

        filter_kwargs = {f"{self.datetime_field}__range": datetime_range.as_tuple()}

        if datetime_range.total_days() < 300:
            truncator = TruncDate
            iterator = datetime_range.iter_days
        else:
            truncator = TruncMonth
            iterator = datetime_range.iter_months

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

        return {date.strftime("%Y-%m-%d"): date_values[date] for date in iterator()}

    def get_chart_data(self) -> dict:
        data = self.get_trend_data()
        trend_labels = list(data.keys())
        trend_data = list(data.values())

        def calculate_trend_line(data):
            """
            Calculate a trend line using basic linear regression.
            :param data: A list of numeric values representing the y-axis.
            :return: A list of trend line values (same length as data).
            """
            if not data or len(data) < 2:
                return (
                    data  # Return the data as-is if not enough points for a trend line
                )

            n = len(data)
            x = list(range(n))
            y = data

            # Calculate the means of x and y
            x_mean = sum(x) / n
            y_mean = sum(y) / n

            # Calculate the slope (m) and y-intercept (b) of the line: y = mx + b
            numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
            denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0
            intercept = y_mean - slope * x_mean

            # Calculate the trend line values
            trend = [slope * xi + intercept for xi in x]

            # if it's all zeros, return nothing
            if all(v == 0 for v in trend):
                return []

            return trend

        return {
            "type": "bar",
            "data": {
                "labels": trend_labels,
                "datasets": [
                    {
                        "data": trend_data,
                    },
                    {
                        "data": calculate_trend_line(trend_data),
                        "type": "line",
                        "borderColor": "rgba(255, 255, 255, 0.3)",
                        "borderWidth": 2,
                        "fill": False,
                        "pointRadius": 0,  # Optional: Hide points
                    },
                ],
            },
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
                    "bar": {"borderRadius": "3", "backgroundColor": "#d6d6d6"}
                },
            },
        }
