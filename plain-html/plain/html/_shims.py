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
    from plain.html import render
    from plain.html.loader import find_template
    from plain.runtime import settings

    path = str(settings.TAILWIND_DIST_PATH.relative_to(_APP_ASSETS_DIR))
    template = find_template("tailwind/css")
    return mark_safe(render(template, {"tailwind_css_path": path}))


def htmx_js(request: Any, extensions: list[str] | None = None) -> SafeString:
    from plain.html import render
    from plain.html.loader import find_template
    from plain.runtime import settings

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


def pageviews_js(request: Any) -> SafeString:
    from plain.html import render
    from plain.html.loader import find_template
    from plain.urls import reverse

    template = find_template("pageviews/js")
    return mark_safe(
        render(
            template,
            {"request": request, "pageviews_track_url": reverse("pageviews:track")},
        )
    )


def toolbar(request: Any) -> SafeString:
    """Render the dev toolbar.

    The outer toolbar template (`toolbar/toolbar.plain`) now renders through
    plain.html. Individual panels still resolve through `Template(name)`, so
    their engine is decided per-file by extension — `.plain` goes through
    plain.html, `.html` falls back to Jinja during migration.
    """
    from plain.html import render
    from plain.html.loader import find_template
    from plain.toolbar.toolbar import Toolbar

    context = {"request": request}
    context["toolbar"] = Toolbar(context)
    template = find_template("toolbar/toolbar")
    return mark_safe(render(template, context))
