from functools import cached_property

from plain.auth.views import AuthViewMixin
from plain.htmx.views import HTMXViewMixin
from plain.http import JsonResponse, Response, ResponseRedirect
from plain.runtime import settings
from plain.views import TemplateView

from .core import Observer
from .models import Trace


class ObserverTracesView(AuthViewMixin, HTMXViewMixin, TemplateView):
    template_name = "observer/traces.html"
    admin_required = True

    @cached_property
    def observer(self):
        """Get the Observer instance for this request."""
        return Observer(self.request)

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
        context["observer"] = self.observer
        context["traces"] = Trace.objects.all()
        if trace_id := self.request.query_params.get("trace_id"):
            context["trace"] = Trace.objects.filter(id=trace_id).first()
        else:
            context["trace"] = context["traces"].first()
        return context

    def get(self):
        # Check if JSON format is requested
        if self.request.query_params.get("format") == "json":
            if trace_id := self.request.query_params.get("trace_id"):
                if trace := Trace.objects.filter(id=trace_id).first():
                    return JsonResponse(trace.as_dict())
            return JsonResponse({"error": "Trace not found"}, status=404)

        return super().get()

    def htmx_post_enable_summary(self):
        """Enable summary mode via HTMX."""
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        self.observer.enable_summary_mode(response)
        return response

    def htmx_post_enable_persist(self):
        """Enable full persist mode via HTMX."""
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        self.observer.enable_persist_mode(response)
        return response

    def htmx_post_disable(self):
        """Disable observer via HTMX."""
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        self.observer.disable(response)
        return response

    def htmx_delete_traces(self):
        """Clear all traces via HTMX DELETE."""
        Trace.objects.all().delete()
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        return response

    def htmx_delete_trace(self):
        """Delete a specific trace via HTMX DELETE."""
        trace_id = self.request.query_params.get("trace_id")
        Trace.objects.get(id=trace_id).delete()
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        return response

    def post(self):
        """A standard, non-htmx post used by the button html (where htmx may not be available)."""

        observe_action = self.request.data["observe_action"]

        response = ResponseRedirect(self.request.data.get("redirect_url", "."))

        if observe_action == "summary":
            self.observer.enable_summary_mode(response)  # Default to summary mode
        elif observe_action == "persist":
            self.observer.enable_persist_mode(response)
        elif observe_action == "disable":
            self.observer.disable(response)

        return response
