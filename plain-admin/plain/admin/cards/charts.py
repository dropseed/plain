from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any

from plain.admin.dates import DatetimeRangeAliases
from plain.postgres.aggregates import Count
from plain.postgres.functions import (
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
    group_field: str | None = None
    group_labels: dict[str, str] | None = None
    group_colors: list[dict[str, str]] = [
        {"bg": "rgba(85, 107, 68, 0.8)", "hover": "rgba(85, 107, 68, 1)"},  # sage
        {
            "bg": "rgba(74, 111, 165, 0.8)",
            "hover": "rgba(74, 111, 165, 1)",
        },  # slate blue
        {
            "bg": "rgba(176, 110, 70, 0.8)",
            "hover": "rgba(176, 110, 70, 1)",
        },  # terracotta
        {
            "bg": "rgba(82, 126, 126, 0.8)",
            "hover": "rgba(82, 126, 126, 1)",
        },  # dusty teal
        {
            "bg": "rgba(140, 100, 75, 0.8)",
            "hover": "rgba(140, 100, 75, 1)",
        },  # warm brown
        {
            "bg": "rgba(130, 100, 140, 0.8)",
            "hover": "rgba(130, 100, 140, 1)",
        },  # muted plum
    ]
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

    def get_trend_data(self) -> dict[str, int] | dict[str, dict[str, int]]:
        """Return trend data, optionally grouped by group_field.

        Without group_field: {date_str: count}
        With group_field: {group_label: {date_str: count}}
        """
        if not self.model or not self.datetime_field:
            raise NotImplementedError(
                "model and datetime_field must be set, or get_trend_data must be overridden"
            )

        datetime_range = DatetimeRangeAliases.to_range(self.get_current_filter())
        filter_kwargs = {f"{self.datetime_field}__range": datetime_range.as_tuple()}

        if datetime_range.total_days() < 300:
            truncator = TruncDate
            iterator = datetime_range.iter_days
        else:
            truncator = TruncMonth
            iterator = datetime_range.iter_months

        value_fields = ["chart_date"]
        if self.group_field:
            value_fields.append(self.group_field)

        rows = (
            self.model.query.filter(**filter_kwargs)
            .annotate(chart_date=truncator(self.datetime_field))
            .values(*value_fields)
            .annotate(chart_date_count=Count("id"))
        )

        dates = list(iterator())

        if not self.group_field:
            date_values: defaultdict[Any, int] = defaultdict(int)
            for row in rows:
                date_values[row["chart_date"]] = row["chart_date_count"]
            return {date.strftime("%Y-%m-%d"): date_values[date] for date in dates}

        labels = self.group_labels or {}

        groups: dict[str, defaultdict[Any, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            raw_value = row[self.group_field]
            label = labels.get(raw_value, raw_value) or "Unknown"
            groups[label][row["chart_date"]] = row["chart_date_count"]

        return {
            group: {date.strftime("%Y-%m-%d"): counts[date] for date in dates}
            for group, counts in sorted(groups.items())
        }

    def get_chart_data(self) -> dict:
        data = self.get_trend_data()

        if self.group_field:
            return self._build_grouped_chart(data)

        return self._build_single_chart(data)

    def _build_single_chart(self, data: dict) -> dict:
        return {
            "type": "bar",
            "data": {
                "labels": list(data.keys()),
                "datasets": [
                    {
                        "data": list(data.values()),
                        "backgroundColor": "rgba(168, 162, 158, 0.7)",  # stone-400
                        "hoverBackgroundColor": "rgba(120, 113, 108, 0.9)",  # stone-500
                        "borderRadius": {"topLeft": 2, "topRight": 2},
                        "borderSkipped": False,
                    },
                ],
            },
            **self._chart_options(show_legend=False, stacked=False),
        }

    def _build_grouped_chart(self, data: dict) -> dict:
        labels = list(next(iter(data.values())).keys())

        datasets = []
        for i, (group_name, date_counts) in enumerate(data.items()):
            colors = self.group_colors[i % len(self.group_colors)]
            datasets.append(
                {
                    "label": str(group_name),
                    "data": list(date_counts.values()),
                    "backgroundColor": colors["bg"],
                    "hoverBackgroundColor": colors["hover"],
                    "borderRadius": {"topLeft": 2, "topRight": 2},
                    "borderSkipped": False,
                }
            )

        return {
            "type": "bar",
            "data": {
                "labels": labels,
                "datasets": datasets,
            },
            **self._chart_options(show_legend=True, stacked=True),
        }

    def _chart_options(self, *, show_legend: bool, stacked: bool) -> dict:
        legend = (
            {
                "display": True,
                "position": "top",
                "align": "end",
                "labels": {
                    "boxWidth": 12,
                    "boxHeight": 12,
                    "borderRadius": 2,
                    "useBorderRadius": True,
                    "padding": 16,
                    "font": {"size": 11},
                },
            }
            if show_legend
            else {"display": False}
        )

        return {
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "animation": {
                    "duration": 600,
                    "easing": "easeOutQuart",
                },
                "plugins": {
                    "legend": legend,
                    "tooltip": {
                        "enabled": True,
                        "backgroundColor": "rgba(41, 37, 36, 0.95)",  # stone-800
                        "titleColor": "rgba(255, 255, 255, 0.7)",
                        "bodyColor": "#ffffff",
                        "bodyFont": {"size": 13, "weight": "600"},
                        "titleFont": {"size": 11},
                        "padding": {"x": 12, "y": 8},
                        "cornerRadius": 6,
                        "displayColors": show_legend,
                    },
                },
                "scales": {
                    "x": {
                        "display": False,
                        "grid": {"display": False},
                        "stacked": stacked,
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
                        "stacked": stacked,
                    },
                },
                "layout": {
                    "padding": {"top": 4, "bottom": 0, "left": 0, "right": 0},
                },
            },
        }
