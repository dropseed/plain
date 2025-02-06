from plain.staff.cards import Card, TrendCard
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffViewset,
    register_viewset,
)

from .models import Pageview


class PageviewsTrendCard(TrendCard):
    title = "Pageviews trend"
    model = Pageview
    datetime_field = "timestamp"
    size = TrendCard.Sizes.FULL


@register_viewset
class PageviewStaff(StaffViewset):
    class ListView(StaffModelListView):
        model = Pageview
        nav_section = "Pageviews"
        title = "Pageviews"
        fields = ["user_id", "url", "timestamp", "session_key"]
        search_fields = ["pk", "user_id", "url", "session_key"]
        cards = [PageviewsTrendCard]

    class DetailView(StaffModelDetailView):
        model = Pageview


class UserPageviewsCard(Card):
    title = "Recent pageviews"
    template_name = "pageviews/card.html"

    def get_template_context(self):
        context = super().get_template_context()

        context["pageviews"] = Pageview.objects.filter(
            user_id=self.view.object.pk
        ).order_by("-timestamp")[:50]

        return context
