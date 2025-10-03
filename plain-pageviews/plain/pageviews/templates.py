from __future__ import annotations

from typing import Any

from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension
from plain.urls import reverse


@register_template_extension
class PageviewsJSExtension(InclusionTagExtension):
    tags = {"pageviews_js"}
    template_name = "pageviews/js.html"

    def get_context(
        self, context: dict[str, Any], *args: Any, **kwargs: Any
    ) -> dict[str, str]:
        return {
            "pageviews_track_url": reverse("pageviews:track"),
        }
