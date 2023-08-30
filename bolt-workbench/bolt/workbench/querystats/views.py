import json
from bolt.views import AuthViewMixin, TemplateView


class QuerystatsView(AuthViewMixin, TemplateView):
    template_name = "querystats/querystats.html"
    staff_required = True  # allow impersonator?

    def get_context(self):
        context = super().get_context()

        stored_querystats = self.request.session.get(
            "querystats"
        )  # Not popping so page can be reloaded
        if stored_querystats:
            # dates won't come back as Python dates...
            stored_querystats = json.loads(stored_querystats)
            context["querystats"] = stored_querystats

        return context

    def get_querystats(self):
        from .middleware import _local

        return _local.querystats
