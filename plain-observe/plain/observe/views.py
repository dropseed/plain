from functools import cached_property

from plain.auth.views import AuthViewMixin
from plain.htmx.views import HTMXViewMixin
from plain.http import Response, ResponseRedirect
from plain.runtime import settings
from plain.views import TemplateView

from .core import Observer
from .models import Trace


class ObservabilitySpansView(AuthViewMixin, HTMXViewMixin, TemplateView):
    template_name = "observability/traces.html"
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

    def htmx_post_enable(self):
        """Enable record-only mode via HTMX."""
        response = Response(self.get_template().render(self.get_template_context()))
        self.observer.enable_record_mode(response)
        return response

    def htmx_post_enable_sample(self):
        """Enable full sampling mode via HTMX."""
        response = Response(self.get_template().render(self.get_template_context()))
        self.observer.enable_sample_mode(response)
        return response

    def htmx_post_disable(self):
        """Disable observability via HTMX."""
        response = Response(self.get_template().render(self.get_template_context()))
        self.observer.disable(response)
        return response

    def htmx_delete_traces(self):
        """Clear all traces via HTMX DELETE."""
        Trace.objects.all().delete()

        return Response(self.render_template())

    def htmx_delete_trace(self):
        """Delete a specific trace via HTMX DELETE."""
        trace_id = self.request.query_params.get("trace_id")
        if trace_id:
            try:
                trace = Trace.objects.get(id=trace_id)
                trace.delete()
            except Trace.DoesNotExist:
                pass

        # Check if there are any traces left after deletion
        remaining_traces = Trace.objects.all()
        if not remaining_traces.exists():
            # If no traces left, refresh the whole page to show empty state
            response = Response(self.render_template())
            response.headers["HX-Refresh"] = "true"
            return response

        return Response(self.render_template())

    def post(self):
        observe_action = self.request.data["observe_action"]

        response = ResponseRedirect(self.request.data.get("redirect_url", "."))
        observer = self.observer

        if observe_action == "enable":
            observer.enable_record_mode(response)  # Default to record mode
        elif observe_action == "enable_sample":
            observer.enable_sample_mode(response)
        elif observe_action == "disable":
            observer.disable(response)

        # Redirect back to the page that submitted the form
        return response
