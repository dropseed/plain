from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, ClassVar, Literal

from plain.admin.dates import DatetimeRangeAliases
from plain.postgres import Model
from plain.postgres.aggregates import Count
from plain.postgres.functions import (
    TruncDate,
    TruncMonth,
)

from ..field_refs import (
    FieldRef,
    converge_declared_field,
    field_lookup_path,
    instance_field_ref,
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

    model: type[Model] | None = None
    # Field references (`JobResult.created_at`, `JobResult.status`) or lookup
    # paths. A reference has to belong to `model`.
    datetime_field: FieldRef | None = None
    group_field: FieldRef | None = None
    group_labels: ClassVar[dict[str, str] | None] = None
    # CSS color values resolved by charts.js. `var(--chart-N)` reads the
    # admin's chart palette so charts retheme automatically (incl. dark mode).
    default_group_colors: tuple[str, ...] = (
        "var(--chart-1)",
        "var(--chart-2)",
        "var(--chart-3)",
        "var(--chart-4)",
        "var(--chart-5)",
    )
    group_colors: ClassVar[dict[str, str] | None] = None
    aggregates: tuple[Literal["sum", "avg", "max"], ...] = ("sum",)
    default_filter = DatetimeRangeAliases.SINCE_30_DAYS_AGO

    filters = DatetimeRangeAliases

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Normalize the declared field references now, so a reference to
        # another model's field is a TypeError at class definition rather than
        # when the card is first rendered, and so no `Field` is left sitting
        # on the class as a live descriptor.
        converge_declared_field(cls, "datetime_field", model=cls.model)
        converge_declared_field(cls, "group_field", model=cls.model)

    def get_datetime_field(self) -> str | None:
        """`datetime_field` as a lookup path, checked against the card's model.

        Read off the instance, so a card that sets its own field takes effect.
        """
        ref = instance_field_ref(self, "datetime_field")
        if ref is None:
            return None
        return field_lookup_path(
            ref,
            model=self.model,
            declared_as=f"{type(self).__qualname__}.datetime_field",
        )

    def get_group_field(self) -> str | None:
        """`group_field` as a lookup path, checked against the card's model."""
        ref = instance_field_ref(self, "group_field")
        if ref is None:
            return None
        return field_lookup_path(
            ref,
            model=self.model,
            declared_as=f"{type(self).__qualname__}.group_field",
        )

    def get_current_filter(self) -> str:
        if s := super().get_current_filter():
            return s
        return self.default_filter.value

    def get_trend_data(self) -> dict[str, int] | dict[str, dict[str, int]]:
        """Return trend data, optionally grouped by group_field.

        Without group_field: {date_str: count}
        With group_field: {group_label: {date_str: count}}
        """
        datetime_field = self.get_datetime_field()
        if self.model is None or datetime_field is None:
            raise NotImplementedError(
                "model and datetime_field must be set, or get_trend_data must be overridden"
            )
        group_field = self.get_group_field()

        datetime_range = DatetimeRangeAliases.to_range(self.get_current_filter())
        filter_kwargs = {f"{datetime_field}__range": datetime_range.as_tuple()}

        if datetime_range.total_days() < 300:
            truncator = TruncDate
            iterator = datetime_range.iter_days
        else:
            truncator = TruncMonth
            iterator = datetime_range.iter_months

        value_fields = ["chart_date"]
        if group_field:
            value_fields.append(group_field)

        rows = (
            self.model.query.filter(**filter_kwargs)
            .annotate(chart_date=truncator(datetime_field))
            .values(*value_fields)
            .annotate(chart_date_count=Count("id"))
        )

        dates = list(iterator())

        if not group_field:
            date_values: defaultdict[Any, int] = defaultdict(int)
            for row in rows:
                date_values[row["chart_date"]] = row["chart_date_count"]
            return {date.strftime("%Y-%m-%d"): date_values[date] for date in dates}

        groups: dict[str, defaultdict[Any, int]] = defaultdict(lambda: defaultdict(int))
        for row in rows:
            raw = row[group_field]
            raw_value = "Unknown" if raw is None else str(raw)
            groups[raw_value][row["chart_date"]] = row["chart_date_count"]

        return {
            group: {date.strftime("%Y-%m-%d"): counts[date] for date in dates}
            for group, counts in sorted(groups.items())
        }

    def get_chart_data(self) -> dict:
        data = self.get_trend_data()

        if self.get_group_field():
            return self._build_grouped_chart(data)

        return self._build_single_chart(data)

    def _build_single_chart(self, data: dict) -> dict:
        return {
            "type": "bar",
            "data": {
                "labels": list(data.keys()),
                "datasets": [
                    {
                        "label": self.title,
                        "data": list(data.values()),
                        "backgroundColor": "var(--chart-1)",
                        "borderRadius": {"topLeft": 2, "topRight": 2},
                        "borderSkipped": False,
                        "categoryPercentage": 0.9,
                        "barPercentage": 1.0,
                    },
                ],
            },
            **self._chart_options(stacked=False),
            "plain": self._plain_meta(),
        }

    def _build_grouped_chart(self, data: dict) -> dict:
        if not data:
            return self._build_single_chart({})

        labels = list(next(iter(data.values())).keys())

        group_labels = self.group_labels or {}

        datasets = []
        for i, (raw_name, date_counts) in enumerate(data.items()):
            display_name = group_labels.get(raw_name, raw_name)
            if self.group_colors and raw_name in self.group_colors:
                color = self.group_colors[raw_name]
            else:
                color = self.default_group_colors[i % len(self.default_group_colors)]
            datasets.append(
                {
                    "label": str(display_name),
                    "data": list(date_counts.values()),
                    "backgroundColor": color,
                    "categoryPercentage": 0.9,
                    "barPercentage": 1.0,
                }
            )

        return {
            "type": "bar",
            "data": {
                "labels": labels,
                "datasets": datasets,
            },
            **self._chart_options(stacked=True),
            "plain": self._plain_meta(),
        }

    def _plain_meta(self) -> dict:
        return {
            "aggregates": list(self.aggregates),
        }

    def _chart_options(self, *, stacked: bool) -> dict:
        return {
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "animation": {
                    "duration": 600,
                    "easing": "easeOutQuart",
                },
                "interaction": {
                    "mode": "index",
                    "intersect": False,
                    "axis": "x",
                },
                "plugins": {
                    "legend": {"display": False},
                    "tooltip": {"enabled": False},
                },
                "scales": {
                    "x": {
                        "display": False,
                        "grid": {"display": False},
                        "stacked": stacked,
                    },
                    "y": {
                        "beginAtZero": True,
                        "display": False,
                        "stacked": stacked,
                    },
                },
                "layout": {
                    "padding": {"top": 4, "bottom": 0, "left": 0, "right": 0},
                },
            },
        }
