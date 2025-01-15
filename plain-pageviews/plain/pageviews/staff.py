from plain.staff.cards import Card, DailyTrendCard
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffModelViewset,
    register_viewset,
)

from .models import Pageview


class DailyPageviewsCard(DailyTrendCard):
    title = "Daily pageviews"
    model = Pageview
    datetime_field = "timestamp"
    size = DailyTrendCard.Sizes.FULL


@register_viewset
class PageviewStaff(StaffModelViewset):
    class ListView(StaffModelListView):
        model = Pageview
        nav_section = "Pageviews"
        title = "Pageviews"
        fields = ["user_id", "url", "timestamp", "session_key"]
        search_fields = ["pk", "user_id", "url", "session_key"]
        cards = [DailyPageviewsCard]

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
