from plain.staff.cards import Card
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffViewset,
    register_viewset,
)

from .models import SupportFormEntry


@register_viewset
class SupportFormEntryStaff(StaffViewset):
    class ListView(StaffModelListView):
        model = SupportFormEntry
        nav_section = "Support"
        title = "Form entries"
        fields = ["user", "email", "name", "form_slug", "created_at"]

    class DetailView(StaffModelDetailView):
        model = SupportFormEntry


class UserSupportFormEntriesCard(Card):
    title = "Recent support"
    template_name = "support/card.html"

    def get_template_context(self):
        context = super().get_template_context()

        context["entries"] = SupportFormEntry.objects.filter(user=self.view.object)

        return context
