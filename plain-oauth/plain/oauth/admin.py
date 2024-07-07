from plain.models import Count
from plain.staff.admin.cards import ChartCard
from plain.staff.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelViewset,
    register_viewset,
)

from .models import OAuthConnection


class ProvidersChartCard(ChartCard):
    title = "Providers"

    def get_chart_data(self) -> dict:
        results = (
            OAuthConnection.objects.all()
            .values("provider_key")
            .annotate(count=Count("id"))
        )
        return {
            "type": "doughnut",
            "data": {
                "labels": [result["provider_key"] for result in results],
                "datasets": [
                    {
                        "label": "Providers",
                        "data": [result["count"] for result in results],
                    }
                ],
            },
        }


@register_viewset
class OAuthConnectionViewset(AdminModelViewset):
    class ListView(AdminModelListView):
        nav_section = "OAuth"
        model = OAuthConnection
        title = "Connections"
        fields = ["id", "user", "provider_key", "provider_user_id"]
        cards = [ProvidersChartCard]

    class DetailView(AdminModelDetailView):
        model = OAuthConnection
        title = "OAuth connection"
