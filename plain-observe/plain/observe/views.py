from plain.auth.views import AuthViewMixin
from plain.http import ResponseRedirect
from plain.runtime import settings
from plain.views import TemplateView

from .models import Trace


class ObservabilitySpansView(AuthViewMixin, TemplateView):
    template_name = "observability/traces.html"
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
        context["observability_enabled"] = self.request.cookies.get("observe") == "true"
        context["traces"] = Trace.objects.all()
        return context

    def post(self):
        observe_action = self.request.data["observe_action"]

        response = ResponseRedirect(self.request.data.get("redirect_url", "."))

        if observe_action == "enable":
            response.set_cookie("observe", "true", max_age=60 * 60 * 24)
            # self.request.session.setdefault(OBSERVABILITY_SESSION_KEY, {})
        elif observe_action == "clear":
            Trace.objects.all().delete()
            # self.request.session[OBSERVABILITY_SESSION_KEY] = {}
        elif observe_action == "disable" and "observe" in self.request.cookies:
            response.delete_cookie("observe")

        # Redirect back to the page that submitted the form
        return response
