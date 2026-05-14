"""Package-helper shims exposed as plain.html globals.

Templates interpolate `{tailwind_css()}` / `{htmx_js(request)}` /
`{pageviews_js(request)}` / `{toolbar(request)}` to render the
corresponding fragment. Each one finds the package's template
(`tailwind/css`, `htmx/js`, etc.) via the plain.html loader and
renders it inline. Eventually these can move into their home
packages and become regular template-side `imports:`.
"""

from __future__ import annotations

from typing import Any

from plain.utils.safestring import SafeString, mark_safe


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
    """Render the dev toolbar, or empty string if plain.toolbar isn't installed.

    Mirrors the original `{% include "toolbar/inject.html" ignore missing %}`
    semantics — templates that interpolate `{toolbar(request)}` keep working
    in projects that haven't installed the toolbar package.
    """
    try:
        from plain.toolbar.toolbar import Toolbar
    except ImportError:
        return mark_safe("")
    from plain.html import render
    from plain.html.loader import find_template

    context = {"request": request}
    context["toolbar"] = Toolbar(context)
    template = find_template("toolbar/toolbar")
    return mark_safe(render(template, context))
