from __future__ import annotations

import json
from typing import Any

from plain.http import JsonResponse, Response, ResponseBase
from plain.json import PlainJSONEncoder
from plain.utils.cache import patch_vary_headers
from plain.views import View


class ReactView(View):
    """
    A view that renders a React component with props instead of a server-side template.

    On the initial page load (standard browser request), returns a full HTML page
    with the React app shell and the page data embedded in a data attribute.

    On subsequent navigations (XHR with X-Plain-React header), returns just the
    JSON page object so the client can swap components without a full page reload.

    Usage:
        class UsersView(ReactView):
            component = "Users/Index"

            def get_props(self):
                return {
                    "users": list(User.query.values("id", "name", "email")),
                }

    SSR (server-side rendering):
        Set ssr = True to render the initial HTML on the server using an
        embedded V8 engine (PyMiniRacer). This eliminates the blank flash
        on initial load — the browser gets fully-rendered HTML that React
        then hydrates.

        Requires: `uv add mini-racer` and a Vite SSR build.

        class UsersView(ReactView):
            component = "Users/Index"
            ssr = True
    """

    # The React component to render (e.g., "Users/Index" resolves to pages/Users/Index.jsx)
    component: str

    # Optional layout component that wraps the page
    layout: str = ""

    # Enable server-side rendering for initial page loads.
    # Requires mini-racer and a built SSR bundle.
    ssr: bool = False

    def get_props(self) -> dict[str, Any]:
        """Override to provide props to the React component."""
        return {}

    def get_shared_props(self) -> dict[str, Any]:
        """
        Props available to every page component.

        Override in a base view class to share data like the authenticated user,
        flash messages, or app-wide configuration.

        Example:
            class AppReactView(ReactView):
                def get_shared_props(self):
                    return {
                        "auth": {"user": get_user_data(self.request)},
                    }
        """
        return {}

    def get_page_data(self, props: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build the page object that gets sent to the client."""
        merged_props = {**self.get_shared_props(), **(props or self.get_props())}
        data: dict[str, Any] = {
            "component": self.component,
            "props": merged_props,
            "url": self.request.get_full_path(),
        }
        if self.layout:
            data["layout"] = self.layout
        return data

    def is_react_request(self) -> bool:
        """Check if this is an SPA navigation request from the React client."""
        return self.request.headers.get("X-Plain-React") == "true"

    def render(self, props: dict[str, Any] | None = None) -> ResponseBase:
        """
        Render the React component.

        For SPA navigations (X-Plain-React header present), returns JSON.
        For initial page loads, returns the full HTML shell with embedded page data.
        """
        page_data = self.get_page_data(props)

        if self.is_react_request():
            response = JsonResponse(page_data)
            response.headers["X-Plain-React"] = "true"
            response.headers["Vary"] = "X-Plain-React"
            return response

        return self._render_html(page_data)

    def _render_html(self, page_data: dict[str, Any]) -> Response:
        """Render the full HTML shell for initial page loads."""
        from .config import get_react_settings

        react_settings = get_react_settings()
        page_json = json.dumps(page_data, cls=PlainJSONEncoder)

        # Server-side render the component if SSR is enabled
        ssr_html = ""
        if self.ssr:
            ssr_html = self._ssr_render(page_data)

        html = _build_html_shell(
            page_json=page_json,
            ssr_html=ssr_html,
            vite_dev_url=react_settings.get("vite_dev_url", ""),
            title=react_settings.get("title", ""),
            head_content=react_settings.get("head", ""),
            root_id=react_settings.get("root_id", "app"),
        )

        response = Response(html)
        response.headers["Vary"] = "X-Plain-React"
        return response

    def _ssr_render(self, page_data: dict[str, Any]) -> str:
        """Render the component to HTML using the embedded V8 engine."""
        from .ssr import render_to_string

        return render_to_string(
            component=page_data["component"],
            props=page_data["props"],
        )

    def get(self) -> ResponseBase:
        return self.render()

    def get_response(self) -> ResponseBase:
        response = super().get_response()
        patch_vary_headers(response, ["X-Plain-React"])
        return response


def _build_html_shell(
    *,
    page_json: str,
    ssr_html: str,
    vite_dev_url: str,
    title: str,
    head_content: str,
    root_id: str,
) -> str:
    """Build the HTML document that bootstraps the React app."""
    from plain.runtime import settings

    # Escape the JSON for safe embedding in an HTML attribute
    escaped_json = (
        page_json.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )

    scripts = ""
    if settings.DEBUG and vite_dev_url:
        # Development: load from Vite dev server
        scripts = f"""<script type="module" src="{vite_dev_url}/@vite/client"></script>
<script type="module" src="{vite_dev_url}/main.jsx"></script>"""
    else:
        # Production: load compiled assets
        from plain.assets.urls import get_asset_url

        try:
            scripts = f'<script type="module" src="{get_asset_url("react/main.js")}"></script>'
        except Exception:
            scripts = '<script type="module" src="/assets/react/main.js"></script>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{f"<title>{title}</title>" if title else ""}
{head_content}
</head>
<body>
<div id="{root_id}" data-page="{escaped_json}">{ssr_html}</div>
{scripts}
</body>
</html>"""
