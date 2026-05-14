from __future__ import annotations

from plain.assets.finders import _APP_ASSETS_DIR
from plain.html import register_global
from plain.html.loader import find_template
from plain.runtime import settings
from plain.utils.safestring import SafeString, mark_safe


@register_global
def tailwind_css() -> SafeString:
    from plain.html import render

    path = str(settings.TAILWIND_DIST_PATH.relative_to(_APP_ASSETS_DIR))
    template = find_template("tailwind/css")
    return mark_safe(render(template, {"tailwind_css_path": path}))
