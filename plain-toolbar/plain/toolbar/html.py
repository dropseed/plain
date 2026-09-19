from __future__ import annotations

from typing import Any

from plain.html.loader import find_template
from plain.utils.safestring import SafeString, mark_safe


def toolbar(request: Any) -> SafeString:
    from plain.html import render

    from .toolbar import Toolbar

    context: dict[str, Any] = {"request": request}
    context["toolbar"] = Toolbar(context)
    template = find_template("toolbar/toolbar")
    return mark_safe(render(template, context))
