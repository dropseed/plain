from plain.models import Count
from plain.staff.cards import ChartCard
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffModelViewset,
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
class OAuthConnectionViewset(StaffModelViewset):
    class ListView(StaffModelListView):
        nav_section = "OAuth"
        model = OAuthConnection
        title = "Connections"
        fields = ["id", "user", "provider_key", "provider_user_id"]
        cards = [ProvidersChartCard]

    class DetailView(StaffModelDetailView):
        model = OAuthConnection
        title = "OAuth connection"
