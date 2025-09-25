from plain.admin.cards import Card, TrendCard
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import Pageview


class PageviewsTrendCard(TrendCard):
    title = "Pageviews trend"
    model = Pageview
    datetime_field = "timestamp"
    size = TrendCard.Sizes.FULL


@register_viewset
class PageviewAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Pageview
        nav_section = "Pageviews"
        nav_icon = "eye"
        title = "Pageviews"
        fields = ["user_id", "url", "source", "timestamp", "session_id"]
        search_fields = ["id", "user_id", "url", "session_id", "source", "medium"]
        cards = [PageviewsTrendCard]

    class DetailView(AdminModelDetailView):
        model = Pageview


class UserPageviewsCard(Card):
    title = "Recent pageviews"
    template_name = "pageviews/card.html"

    def get_template_context(self):
        context = super().get_template_context()

        context["pageviews"] = Pageview.query.filter(
            user_id=self.view.object.id
        ).order_by("-timestamp")[:50]

        return context
