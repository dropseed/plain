import json

from plain.auth.views import AuthViewMixin
from plain.http import ResponseRedirect
from plain.views import TemplateView


class QuerystatsView(AuthViewMixin, TemplateView):
    template_name = "querystats/querystats.html"
    admin_required = True

    def get_template_context(self):
        context = super().get_template_context()

        querystats = self.request.session.get("querystats", {})

        for request_id, json_data in querystats.items():
            try:
                querystats[request_id] = json.loads(json_data)
            except json.JSONDecodeError:
                # If decoding fails, remove the entry from the dictionary
                del querystats[request_id]

        # Order them by timestamp
        querystats = dict(
            sorted(
                querystats.items(),
                key=lambda item: item[1].get("timestamp", ""),
                reverse=True,
            )
        )

        context["querystats"] = querystats

        return context

    def post(self):
        querystats_action = self.request.POST["querystats_action"]

        if querystats_action == "enable":
            self.request.session.setdefault("querystats", {})
        elif querystats_action == "clear":
            self.request.session["querystats"] = {}
        elif querystats_action == "disable" and "querystats" in self.request.session:
            del self.request.session["querystats"]

        # Redirect back to the page that submitted the form
        return ResponseRedirect(self.request.POST.get("redirect_url", "."))
