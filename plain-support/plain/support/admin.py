from __future__ import annotations

from typing import Any

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
        nav_icon = "headset"
        title = "Form entries"
        fields = ["user", "email", "name", "form_slug", "created_at"]

    class DetailView(AdminModelDetailView):
        model = SupportFormEntry


class UserSupportFormEntriesCard(Card):
    title = "Recent support"
    template_name = "support/card.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()

        # self.view has an object attribute when used in DetailView context
        context["entries"] = SupportFormEntry.query.filter(
            user=self.view.object  # type: ignore[attr-defined]
        )

        return context
