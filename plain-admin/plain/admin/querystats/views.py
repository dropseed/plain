import json

from plain.auth.views import AuthViewMixin
from plain.http import ResponseRedirect
from plain.runtime import settings
from plain.views import TemplateView


class QuerystatsView(AuthViewMixin, TemplateView):
    template_name = "querystats/querystats.html"
    admin_required = True

    def check_auth(self):
        # Allow the view if we're in DEBUG
        if settings.DEBUG:
            return

        super().check_auth()

    def get_response(self):
        response = super().get_response()
        # So we can load it in the toolbar
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    def get(self):
        # Give an easy out if things get messed up
        if (
            "clear" in self.request.query_params
            and "querystats" in self.request.session
        ):
            del self.request.session["querystats"]
            self.request.session.modified = True

        return super().get()

    def get_template_context(self):
        context = super().get_template_context()

        querystats = self.request.session.get("querystats", {})

        for request_id in list(querystats.keys()):
            try:
                querystats[request_id] = json.loads(querystats[request_id])
            except (json.JSONDecodeError, TypeError):
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
        context["querystats_enabled"] = "querystats" in self.request.session

        return context

    def post(self):
        querystats_action = self.request.data["querystats_action"]

        if querystats_action == "enable":
            self.request.session.setdefault("querystats", {})
        elif querystats_action == "clear":
            self.request.session["querystats"] = {}
        elif querystats_action == "disable" and "querystats" in self.request.session:
            del self.request.session["querystats"]

        # Redirect back to the page that submitted the form
        return ResponseRedirect(self.request.data.get("redirect_url", "."))
