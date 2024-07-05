import datetime
import plotly.express as px
import pandas as pd
from .base import Card
from bolt.db.models import Count
from bolt.db.models.functions import TruncDate

class Chart:
    def render_html(self):
        config = {
            "displayModeBar": False,
            "scrollZoom": False,
            "responsive": True,
            # "staticPlot": True,
        }
        return self.get_figure().to_html(full_html=False, config=config)#, include_plotlyjs=False)

    def render_image(self):
        return self.get_figure().to_image(format="png")

    def __html__(self):
        return self.render_html()


class BarChart(Chart):
    def __init__(self, *, dataframe, x, y):
        self.dataframe = dataframe
        self.x = x
        self.y = y

    def get_figure(self):
        fig = px.bar(self.dataframe, x=self.x, y=self.y)
        return fig



class TrendCard(Card):
    template_name = "admin/cards/trend.html"

    model = None
    trend_field = "created_at"

    # default behavior can be querysets and  models?
    # override if custom objects, but rare?

    def get_template_context(self):
        context = super().get_template_context()
        context["chart"] = self.get_chart()
        return context

    def get_chart(self):
        filters = {
            f"{self.trend_field}__range": self.datetime_range.as_tuple(),
        }
        data = (
            self.model.objects.filter(**filters)
            .annotate(date=TruncDate(self.trend_field))
            .values("date")
            .annotate(count=Count("id"))
            .order_by("date")
        )

        dataframe = pd.DataFrame.from_records(
            data,
            columns=["date", "count"],
        )

        # fill the zeroes for the missing dates
        dataframe = dataframe.set_index("date").reindex(self.datetime_range).fillna(0).reset_index()

        return BarChart(
            dataframe=dataframe,
            x="date",
            y="count",
        )


class ChartCard(Card):
    template_name = "admin/cards/chart.html"

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
