from plain.admin.cards import Card
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import SupportFormEntry


@register_viewset
class SupportFormEntryAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = SupportFormEntry
        nav_section = "Support"
        title = "Form entries"
        fields = ["user", "email", "name", "form_slug", "created_at"]

    class DetailView(AdminModelDetailView):
        model = SupportFormEntry


class UserSupportFormEntriesCard(Card):
    title = "Recent support"
    template_name = "support/card.html"

    def get_template_context(self):
        context = super().get_template_context()

        context["entries"] = SupportFormEntry.objects.filter(user=self.view.object)

        return context
