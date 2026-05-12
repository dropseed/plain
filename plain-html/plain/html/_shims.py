"""Bridges to existing Jinja-rendered package templates.

The migration plan ports package templates to `.plain` over many phases. In
the meantime, templates that already render through `plain.html` need a way
to invoke package helpers (`tailwind_css`, `pageviews_js`, `toolbar`) whose
internals are still Jinja. These shims render the underlying Jinja template
on demand and return `Markup` so plain.html doesn't re-escape the HTML.
"""

from __future__ import annotations

from typing import Any

from plain.utils.safestring import SafeString, mark_safe


def _render_jinja(template_name: str, context: dict[str, Any]) -> SafeString:
    from plain.templates.jinja import environment

    template = environment.get_template(template_name)
    return mark_safe(template.render(context))


def tailwind_css() -> SafeString:
    from plain.assets.finders import _APP_ASSETS_DIR
    from plain.runtime import settings

    path = str(settings.TAILWIND_DIST_PATH.relative_to(_APP_ASSETS_DIR))
    return _render_jinja("tailwind/css.html", {"tailwind_css_path": path})


def pageviews_js(request: Any) -> SafeString:
    from plain.urls import reverse

    return _render_jinja(
        "pageviews/js.html",
        {"request": request, "pageviews_track_url": reverse("pageviews:track")},
    )


def toolbar(request: Any) -> SafeString:
    """Render the dev toolbar via the existing Jinja path.

    The toolbar templates and `Toolbar` class are still Jinja-bound. We build
    the same toolbar object here and hand it to the Jinja environment so the
    output matches the pre-migration rendering. Porting the toolbar end-to-end
    is a later phase.
    """
    from plain.toolbar.toolbar import Toolbar

    context = {"request": request}
    context["toolbar"] = Toolbar(context)
    return _render_jinja("toolbar/toolbar.html", context)
