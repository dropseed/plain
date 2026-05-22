from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.trace import format_trace_id

from plain.runtime import settings
from plain.toolbar import ToolbarItem, register_toolbar_item


@register_toolbar_item
class ConnectToolbarItem(ToolbarItem):
    """Links the current request to its exported trace in Plain Cloud.

    This module is only imported when plain.toolbar is installed (it is
    autodiscovered by the toolbar package), so the import above is safe
    without a guard. The item is a button-only toolbar entry — no panel —
    that points at the `/t/<trace_id>` short URL on the dashboard, which
    resolves the trace back to its app and redirects.
    """

    name = "Connect"
    button_template_name = "toolbar/connect_button.html"

    def is_enabled(self) -> bool:
        """Only show the item when connect is actively exporting."""
        return bool(settings.CONNECT_EXPORT_ENABLED and settings.CONNECT_EXPORT_TOKEN)

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()

        span_context = trace.get_current_span().get_span_context()
        if not span_context.is_valid:
            context["sampled"] = None
            context["trace_url"] = ""
            return context

        # The sampled flag reflects the final sampling decision, so a
        # sub-1.0 CONNECT_TRACE_SAMPLE_RATE is accounted for here for free.
        context["sampled"] = span_context.trace_flags.sampled
        if span_context.trace_flags.sampled:
            dashboard_url = str(settings.CONNECT_DASHBOARD_URL).rstrip("/")
            trace_id = format_trace_id(span_context.trace_id)
            context["trace_url"] = f"{dashboard_url}/t/{trace_id}"
        else:
            context["trace_url"] = ""

        return context
