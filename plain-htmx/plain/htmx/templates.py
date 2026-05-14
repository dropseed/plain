from __future__ import annotations

from typing import Any

from plain.html import register_global
from plain.html.loader import find_template
from plain.runtime import settings
from plain.utils.safestring import SafeString, mark_safe


@register_global
def htmx_js(request: Any, extensions: list[str] | None = None) -> SafeString:
    from plain.html import render

    template = find_template("htmx/js")
    return mark_safe(
        render(
            template,
            {
                "DEBUG": settings.DEBUG,
                "extensions": extensions or [],
                "csp_nonce": request.csp_nonce,
            },
        )
    )
