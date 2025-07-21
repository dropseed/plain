from plain.auth.views import AuthViewMixin
from plain.htmx.views import HTMXViewMixin
from plain.http import JsonResponse, Response
from plain.runtime import settings
from plain.urls import reverse
from plain.views import DetailView, ListView

from .core import Observer
from .models import Trace


class ObserverTracesView(AuthViewMixin, HTMXViewMixin, ListView):
    template_name = "observer/traces.html"
    context_object_name = "traces"
    admin_required = True

    def get_objects(self):
        return Trace.objects.all()

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
        context["observer"] = Observer(self.request)
        return context

    def htmx_put_mode(self):
        """Set observer mode via HTMX PUT."""
        mode = self.request.data.get("mode")
        observer = Observer(self.request)

        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"

        if mode == "summary":
            observer.enable_summary_mode(response)
        elif mode == "persist":
            observer.enable_persist_mode(response)
        elif mode == "disable":
            observer.disable(response)
        else:
            return Response("Invalid mode", status_code=400)

        return response

    def htmx_delete_traces(self):
        """Clear all traces via HTMX DELETE."""
        Trace.objects.filter(share_id="").delete()
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        return response


class ObserverTraceDetailView(AuthViewMixin, HTMXViewMixin, DetailView):
    """Detail view for a specific trace."""

    template_name = "observer/trace_detail.html"
    context_object_name = "trace"
    admin_required = True

    def get_object(self):
        return Trace.objects.get_or_none(trace_id=self.url_kwargs.get("trace_id"))

    def check_auth(self):
        # Allow the view if we're in DEBUG
        if settings.DEBUG:
            return
        super().check_auth()

    def get(self):
        """Return trace data as HTML or JSON based on content negotiation."""
        if (
            "application/json" in self.request.headers.get("Accept", "")
            or self.request.query_params.get("format") == "json"
        ):
            return self.get_object().as_dict()

        return super().get()

    def get_template_names(self):
        if self.is_htmx_request():
            # Use a different template for HTMX requests
            return ["observer/trace.html"]
        return super().get_template_names()

    def htmx_delete(self):
        trace = self.get_object()
        trace.delete()

        # Redirect to traces list after deletion
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = reverse("observer:traces")
        return response

    def htmx_post_share(self):
        trace = self.get_object()
        trace.generate_share_id()
        return super().get()

    def htmx_delete_share(self):
        trace = self.get_object()
        trace.remove_share_id()
        return super().get()


class ObserverTraceSharedView(DetailView):
    """Public view for shared trace data."""

    template_name = "observer/trace_share.html"
    context_object_name = "trace"

    def get_object(self):
        return Trace.objects.get_or_none(share_id=self.url_kwargs["share_id"])

    def get_template_context(self):
        context = super().get_template_context()
        context["is_share_view"] = True
        return context

    def get(self):
        """Return trace data as HTML or JSON based on content negotiation."""
        if (
            "application/json" in self.request.headers.get("Accept", "")
            or self.request.query_params.get("format") == "json"
        ):
            return JsonResponse(self.get_object().as_dict())

        return super().get()
