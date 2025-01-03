from plain.staff.cards import Card
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffModelViewset,
    register_viewset,
)

from .models import Pageview


@register_viewset
class PageviewStaff(StaffModelViewset):
    class ListView(StaffModelListView):
        model = Pageview
        nav_section = "Pageviews"
        title = "Pageviews"
        fields = ["user_id", "url", "timestamp", "session_key"]
        # search_fields = ["uuid", "url", "session_key"]
        # ordering = ["-timestamp"]
        # list_display = ["uuid", "user", "url", "timestamp", "session_key"]
        # list_filter = ["user", "url", "timestamp", "session_key"]
        # date_hierarchy = "timestamp"
        # actions = ["delete_selected"]

        # def get_queryset(self, request):
        #     return super().get_queryset(request).select_related("user")

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
