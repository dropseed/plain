import datetime

from .base import Card


class ChartCard(Card):
    template_name = "staff/cards/chart.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["chart_data"] = self.get_chart_data()
        return context

    def get_chart_data(self) -> dict:
        raise NotImplementedError


class DailyTrendCard(ChartCard):
    def get_values(self) -> dict[datetime.date, int]:
        raise NotImplementedError

    def get_chart_data(self) -> dict:
        date_labels = [date.strftime("%Y-%m-%d") for date in self.datetime_range]
        date_values = self.get_values()
        # Convert all to dates
        # date_values = {
        #     date.date() if isinstance(date, datetime.datetime) else date: value
        #     for date, value in date_values.items()
        # }

        for date in self.datetime_range:
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
