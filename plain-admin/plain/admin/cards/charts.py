from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from plain.admin.dates import DatetimeRangeAliases
from plain.models.aggregates import Count
from plain.models.functions import (
    TruncDate,
    TruncMonth,
)

from .base import Card


class ChartCard(Card, ABC):
    template_name = "admin/cards/chart.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["chart_data"] = self.get_chart_data()
        return context

    @abstractmethod
    def get_chart_data(self) -> dict: ...


class TrendCard(ChartCard):
    """
    A card that renders a trend chart.
    Primarily intended for use with models, but it can also be customized.
    """

    model = None
    datetime_field = None
    default_filter = DatetimeRangeAliases.SINCE_30_DAYS_AGO

    filters = DatetimeRangeAliases

    def get_description(self) -> str:
        datetime_range = DatetimeRangeAliases.to_range(self.get_current_filter())
        start = datetime_range.start.strftime("%b %d, %Y")
        end = datetime_range.end.strftime("%b %d, %Y")
        return f"{start} to {end}"

    def get_current_filter(self) -> str:
        if s := super().get_current_filter():
            return s
        return self.default_filter.value

    def get_trend_data(self) -> dict[str, int]:
        if not self.model or not self.datetime_field:
            raise NotImplementedError(
                "model and datetime_field must be set, or get_values must be overridden"
            )

        datetime_range = DatetimeRangeAliases.to_range(self.get_current_filter())

        filter_kwargs = {f"{self.datetime_field}__range": datetime_range.as_tuple()}

        if datetime_range.total_days() < 300:
            truncator = TruncDate
            iterator = datetime_range.iter_days
        else:
            truncator = TruncMonth
            iterator = datetime_range.iter_months

        counts_by_date = (
            self.model.query.filter(**filter_kwargs)
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

        return {
            "type": "bar",
            "data": {
                "labels": trend_labels,
                "datasets": [
                    {
                        "data": trend_data,
                        # Gradient will be applied via JS - this is the fallback
                        "backgroundColor": "rgba(168, 162, 158, 0.7)",  # stone-400
                        "hoverBackgroundColor": "rgba(120, 113, 108, 0.9)",  # stone-500
                        "borderRadius": {"topLeft": 4, "topRight": 4},
                        "borderSkipped": False,
                    },
                ],
            },
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "animation": {
                    "duration": 600,
                    "easing": "easeOutQuart",
                },
                "plugins": {
                    "legend": {"display": False},
                    "tooltip": {
                        "enabled": True,
                        "backgroundColor": "rgba(41, 37, 36, 0.95)",  # stone-800
                        "titleColor": "rgba(255, 255, 255, 0.7)",
                        "bodyColor": "#ffffff",
                        "bodyFont": {"size": 13, "weight": "600"},
                        "titleFont": {"size": 11},
                        "padding": {"x": 12, "y": 8},
                        "cornerRadius": 6,
                        "displayColors": False,
                    },
                },
                "scales": {
                    "x": {
                        "display": False,
                        "grid": {"display": False},
                    },
                    "y": {
                        "beginAtZero": True,
                        "display": True,
                        "position": "right",
                        "grid": {
                            "display": True,
                            "color": "rgba(0, 0, 0, 0.04)",
                            "drawTicks": False,
                        },
                        "border": {"display": False},
                        "ticks": {
                            "display": False,
                            "maxTicksLimit": 4,
                        },
                    },
                },
                "layout": {
                    "padding": {"top": 4, "bottom": 0, "left": 0, "right": 0},
                },
            },
        }
