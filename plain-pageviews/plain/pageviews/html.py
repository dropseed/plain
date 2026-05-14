from __future__ import annotations

from typing import Any

from plain.html.loader import find_template
from plain.urls import reverse
from plain.utils.safestring import SafeString, mark_safe


def pageviews_js(request: Any) -> SafeString:
    from plain.html import render

    template = find_template("pageviews/js")
    return mark_safe(
        render(
            template,
            {"request": request, "pageviews_track_url": reverse("pageviews:track")},
        )
    )
