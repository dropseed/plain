from bolt.http import HttpResponseRedirect
from bolt.urls import reverse

from ..models import Dashboard
from .base import AdminPageView
from .registry import registry

# class MissingCardView(AdminTextCardView):
#     title = "Missing card"

#     def __init__(self, *args, missing_card_slug, **kwargs):
#         self.missing_card_slug = missing_card_slug
#         super().__init__(*args, **kwargs)

#     def get_text(self) -> str:
#         return f"Missing card with slug '{self.missing_card_slug}'"


# This will be dashboard view...
class AdminIndexView(AdminPageView):
    template_name = "admin/dashboard.html"
    title = "Admin"
    slug = ""

    def get_context(self):
        context = super().get_context()

        dashboard = Dashboard.objects.first()
        if not dashboard:
            dashboard = Dashboard.objects.create(
                name="Default",
            )

        context["dashboard"] = dashboard
        context["title"] = dashboard.name
        context["description"] = dashboard.description

        cards = []

        # Use the order that the dashboard has
        for card in dashboard.cards:
            card_slug = card["slug"]
            try:
                card = [
                    c for c in registry.registered_cards if c.get_slug() == card_slug
                ][0]
            except IndexError:
                # card = MissingCardView(self.request, missing_card_slug=card_slug)
                continue

            cards.append(card)

        context["cards"] = cards

        return context

    def post(self):
        card_slug = self.request.POST.get("card")
        dashboard = Dashboard.objects.first()
        dashboard.cards = dashboard.cards + [{"slug": card_slug}]
        dashboard.save()
        return HttpResponseRedirect(reverse("admin:index"))
