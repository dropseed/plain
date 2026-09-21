from dataclasses import dataclass

from plain.admin.cards import ChartCard
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import OAuthConnection


@dataclass
class ProviderCount:
    provider_key: str
    count: int


class ProvidersChartCard(ChartCard):
    title = "Providers"

    def get_chart_data(self) -> dict:
        results = OAuthConnection.query.sql(
            t"""
            SELECT {OAuthConnection.provider_key} AS provider_key,
                   count(*) AS "count!"
            FROM {OAuthConnection}
            GROUP BY 1
            ORDER BY 1
            """,
            result_type=ProviderCount,
        ).all()
        return {
            "type": "doughnut",
            "data": {
                "labels": [result.provider_key for result in results],
                "datasets": [
                    {
                        "label": "Providers",
                        "data": [result.count for result in results],
                    }
                ],
            },
        }


@register_viewset
class OAuthConnectionViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "OAuth"
        nav_icon = "link-45deg"
        model = OAuthConnection
        title = "Connections"
        description = "User accounts linked to OAuth providers (Google, GitHub, etc)."
        fields = ("id", "user", "provider_key", "provider_user_id")
        cards = (ProvidersChartCard,)

    class DetailView(AdminModelDetailView):
        model = OAuthConnection
        title = "OAuth connection"
