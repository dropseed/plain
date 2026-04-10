from __future__ import annotations

from functools import cached_property
from typing import Any

from plain.assets.views import AssetView
from plain.http import (
    NotFoundError404,
    RedirectResponse,
    Response,
)
from plain.runtime import settings
from plain.utils.cache import patch_vary_headers
from plain.views import TemplateView, View

from .exceptions import PageNotFoundError, RedirectPageError
from .pages import Page
from .registry import pages_registry

__all__ = ["PageView"]


class PageViewMixin:
    @cached_property
    def page(self) -> Page:
        url_name = self.request.resolver_match.url_name  # ty: ignore[unresolved-attribute]

        try:
            return pages_registry.get_page_from_name(url_name)
        except PageNotFoundError:
            raise NotFoundError404()

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()  # ty: ignore[unresolved-attribute]
        context["page"] = self.page
        self.page.set_template_context(context)  # Pass the standard context through
        return context


class PageView(PageViewMixin, TemplateView):
    template_name = "page.html"

    def _markdown_response(self, page: Page) -> Response:
        """Build a plain-text markdown response with Vary header."""
        context = {**self.get_template_context(), "page": page}
        page.set_template_context(context)
        markdown_content = page.rendered_source(context)
        response = Response(markdown_content, content_type="text/plain; charset=utf-8")
        patch_vary_headers(response, ["Accept"])
        return response

    def _prefers_markdown(self, *types: str) -> bool:
        """Check if the request prefers markdown over the given types."""
        preferred = self.request.get_preferred_type(*types)
        return preferred in ("text/markdown", "text/plain")

    def get(self) -> Response:
        """Check Accept header and serve markdown if requested."""
        if not settings.PAGES_SERVE_MARKDOWN:
            return super().get()

        # Standalone markdown page -- markdown is preferred by default.
        # Type order matters: first type listed wins ties, so markdown
        # types come first here to default to raw markdown.
        if self.page.is_markdown():
            if self._prefers_markdown("text/markdown", "text/plain", "text/html"):
                return self._markdown_response(self.page)
            response = super().get()
            patch_vary_headers(response, ["Accept"])
            return response

        # HTML page -- only serve markdown if a companion exists and is explicitly preferred.
        # Type order matters: text/html first so HTML wins ties.
        url_name = self.page.get_url_name()
        if not url_name:
            return super().get()

        companion = pages_registry.get_markdown_companion(url_name)
        if not companion:
            return super().get()

        if self._prefers_markdown("text/html", "text/markdown", "text/plain"):
            return self._markdown_response(companion)

        # HTML response varies by Accept when a companion exists
        response = super().get()
        patch_vary_headers(response, ["Accept"])
        return response

    def get_template_names(self) -> list[str]:
        """
        Allow for more specific user templates like
        markdown.html or html.html
        """
        if template_name := self.page.get_template_name():
            return [template_name]

        return super().get_template_names()


class PageRedirectView(PageViewMixin, View):
    def get(self) -> RedirectResponse:
        url = self.page.vars.get("url")

        if not url:
            raise RedirectPageError("Redirect page is missing a url")

        status_code = self.page.vars.get("status_code", 302)
        return RedirectResponse(url, status_code=status_code, allow_external=True)


class PageAssetView(PageViewMixin, AssetView):
    def get_url_path(self) -> str | None:
        return self.page.get_url_path()

    def get_asset_path(self, path: str) -> str:
        return self.page.absolute_path

    def get_debug_asset_path(self, path: str) -> str:
        return self.page.absolute_path


class PageMarkdownView(PageViewMixin, TemplateView):
    def get(self) -> Response:
        """Serve the markdown content without frontmatter."""
        context = self.get_template_context()
        markdown_content = self.page.rendered_source(context)
        return Response(markdown_content, content_type="text/plain; charset=utf-8")
