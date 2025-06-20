from plain.auth.views import AuthViewMixin
from plain.runtime import settings
from plain.views import TemplateView

# from .middleware import OBSERVABILITY_SESSION_KEY


class ObservabilitySpansView(AuthViewMixin, TemplateView):
    template_name = "observability/spans.html"
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

    def get_template_context(self):
        context = super().get_template_context()

        # observability = self.request.session.get(OBSERVABILITY_SESSION_KEY, {})

        # for request_id in list(spans.keys()):
        #     try:
        #         spans[request_id] = json.loads(spans[request_id])
        #     except (json.JSONDecodeError, TypeError):
        #         # If decoding fails, remove the entry from the dictionary
        #         del spans[request_id]

        # Order them by timestamp
        # spans = dict(
        #     sorted(
        #         spans.items(),
        #         key=lambda item: item[1].get("timestamp", ""),
        #         reverse=True,
        #     )
        # )

        # context["observability"] = observability
        # context["observability_enabled"] = OBSERVABILITY_SESSION_KEY in self.request.session

        return context

    # def post(self):
    #     querystats_action = self.request.data["querystats_action"]

    #     if querystats_action == "enable":
    #         self.request.session.setdefault(OBSERVABILITY_SESSION_KEY, {})
    #     elif querystats_action == "clear":
    #         self.request.session[OBSERVABILITY_SESSION_KEY] = {}
    #     elif querystats_action == "disable" and OBSERVABILITY_SESSION_KEY in self.request.session:
    #         del self.request.session[OBSERVABILITY_SESSION_KEY]

    #     # Redirect back to the page that submitted the form
    #     return ResponseRedirect(self.request.data.get("redirect_url", "."))
