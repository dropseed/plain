from __future__ import annotations

from typing import Any

from plain.runtime import settings
from plain.toolbar import ToolbarItem, register_toolbar_item

from .tracing import current_trace


@register_toolbar_item
class ConnectToolbarItem(ToolbarItem):
    """Links the current request to its exported trace in Plain Cloud.

    This module is only imported when plain.toolbar is installed (it is
    autodiscovered by the toolbar package), so the `plain.toolbar` import
    above is safe without a guard. The item is a button-only toolbar entry —
    no panel — that points at the `/t/<trace_id>` short URL on the dashboard,
    which resolves the trace back to its app and redirects.
    """

    name = "Connect"
    button_template_name = "toolbar/connect_button.html"

    def is_enabled(self) -> bool:
        """Only show the item when connect is actively exporting."""
        return bool(settings.CONNECT_EXPORT_ENABLED and settings.CONNECT_EXPORT_TOKEN)

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()

        trace = current_trace()
        context["sampled"] = trace.sampled
        if trace.sampled:
            cloud_url = str(settings.CONNECT_CLOUD_URL).rstrip("/")
            context["trace_url"] = f"{cloud_url}/t/{trace.trace_id}"
        else:
            context["trace_url"] = ""

        return context
