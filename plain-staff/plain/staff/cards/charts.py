import datetime

from plain.models import Count
from plain.models.functions import TruncDate
from plain.staff.dates import DatetimeRangeAliases

from .base import Card


class ChartCard(Card):
    template_name = "staff/cards/chart.html"
    datetime_range = True

    def get_template_context(self):
        context = super().get_template_context()
        context["chart_data"] = self.get_chart_data()
        return context

    def get_chart_data(self) -> dict:
        raise NotImplementedError


class DailyTrendCard(ChartCard):
    model = None
    datetime_field = None

    def get_values(self) -> dict[datetime.date, int]:
        if not self.model or not self.datetime_field:
            raise NotImplementedError(
                "model and datetime_field must be set, or get_values must be overridden"
            )

        datetime_range = DatetimeRangeAliases.to_range(
            DatetimeRangeAliases.SINCE_30_DAYS_AGO
        ).as_tuple()

        filter_kwargs = {f"{self.datetime_field}__range": datetime_range}

        counts_by_date = (
            self.model.objects.filter(**filter_kwargs)
            .annotate(chart_date=TruncDate(self.datetime_field))
            .values("chart_date")
            .annotate(chart_date_count=Count("id"))
            .order_by("chart_date")
        )

        return {row["chart_date"]: row["chart_date_count"] for row in counts_by_date}

    def get_chart_data(self) -> dict:
        datetime_range = DatetimeRangeAliases.to_range(
            DatetimeRangeAliases.SINCE_30_DAYS_AGO
        )

        date_labels = [date.strftime("%Y-%m-%d") for date in datetime_range]
        date_values = self.get_values()
        # Convert all to dates
        # date_values = {
        #     date.date() if isinstance(date, datetime.datetime) else date: value
        #     for date, value in date_values.items()
        # }

        for date in datetime_range:
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
                        "suggestedMin": 0,
                    },
                },
                "maintainAspectRatio": False,
                "elements": {
                    "bar": {"borderRadius": "3", "backgroundColor": "rgb(28, 25, 23)"}
                },
            },
        }
