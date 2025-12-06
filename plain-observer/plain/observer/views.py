from __future__ import annotations

from typing import Any

from plain import models
from plain.auth.views import AuthView
from plain.htmx.views import HTMXView
from plain.http import Response, ResponseBase
from plain.runtime import settings
from plain.urls import reverse
from plain.views import DetailView, ListView

from .core import Observer
from .models import Trace


class ObserverTracesView(AuthView, HTMXView, ListView):
    template_name = "observer/traces.html"
    context_object_name = "traces"
    admin_required = True

    def get_objects(self) -> models.QuerySet:
        return Trace.query.all()

    def check_auth(self) -> None:
        # Allow the view if we're in DEBUG
        if settings.DEBUG:
            return

        super().check_auth()

    def get_response(self) -> ResponseBase:
        response = super().get_response()
        # So we can load it in the toolbar
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["observer"] = Observer.from_request(self.request)
        return context

    def htmx_put_mode(self) -> Response:
        """Set observer mode via HTMX PUT."""
        mode = self.request.form_data.get("mode")
        observer = Observer.from_request(self.request)

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

    def htmx_delete_traces(self) -> Response:
        """Clear all traces via HTMX DELETE."""
        Trace.query.all().delete()
        response = Response(status_code=204)
        response.headers["HX-Refresh"] = "true"
        return response

    def post(self) -> Response:
        """Handle POST requests to set observer mode."""
        action = self.request.form_data.get("observe_action")
        if action == "summary":
            observer = Observer.from_request(self.request)
            response = Response(status_code=204)
            observer.enable_summary_mode(response)
            return response
        return Response("Invalid action", status_code=400)


class ObserverTraceDetailView(AuthView, HTMXView, DetailView):
    """Detail view for a specific trace."""

    template_name = "observer/trace_detail.html"
    context_object_name = "trace"
    admin_required = True

    def get_object(self) -> Trace | None:
        return Trace.query.get_or_none(trace_id=self.url_kwargs.get("trace_id"))

    def check_auth(self) -> None:
        # Allow the view if we're in DEBUG
        if settings.DEBUG:
            return
        super().check_auth()

    def get(self) -> Response | dict[str, Any]:
        """Return trace data as HTML, JSON, or logs based on content negotiation."""
        preferred = self.request.get_preferred_type("text/html", "application/json")
        if (
            preferred == "application/json"
            or self.request.query_params.get("format") == "json"
        ):
            return self.object.as_dict()

        if self.request.query_params.get("logs") == "true":
            logs = self.object.logs.query.all().order_by("timestamp")
            log_lines = []
            for log in logs:
                timestamp = log.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
                log_lines.append(f"{timestamp} [{log.level}]: {log.message}")

            return Response("\n".join(log_lines), content_type="text/plain")

        return super().get()

    def get_template_names(self) -> list[str]:
        if self.is_htmx_request():
            # Use a different template for HTMX requests
            return ["observer/trace.html"]
        return super().get_template_names()

    def htmx_delete(self) -> Response:
        self.object.delete()

        # Redirect to traces list after deletion
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = reverse("observer:traces")
        return response
