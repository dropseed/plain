from functools import cached_property

from plain.assets.views import AssetView
from plain.http import (
    Http404,
    Response,
    ResponseRedirect,
)
from plain.runtime import settings
from plain.views import TemplateView, View

from .exceptions import PageNotFoundError, RedirectPageError
from .registry import pages_registry


class PageViewMixin:
    @cached_property
    def page(self):
        url_name = self.request.resolver_match.url_name

        try:
            return pages_registry.get_page_from_name(url_name)
        except PageNotFoundError:
            raise Http404()


class PageView(PageViewMixin, TemplateView):
    template_name = "page.html"

    def get(self):
        """Check Accept header and serve markdown if requested."""
        if self.page.is_markdown() and settings.PAGES_SERVE_MARKDOWN:
            preferred = self.request.get_preferred_type(
                "text/markdown", "text/plain", "text/html"
            )
            if preferred in ("text/markdown", "text/plain"):
                markdown_content = self.page._frontmatter.content
                response = Response(
                    markdown_content, content_type="text/plain; charset=utf-8"
                )
                response.headers["Vary"] = "Accept"
                return response

        return super().get()

    def get_template_names(self) -> list[str]:
        """
        Allow for more specific user templates like
        markdown.html or html.html
        """
        if template_name := self.page.get_template_name():
            return [template_name]

        return super().get_template_names()

    def get_template_context(self):
        context = super().get_template_context()
        context["page"] = self.page
        self.page.set_template_context(context)  # Pass the standard context through
        return context


class PageRedirectView(PageViewMixin, View):
    def get(self):
        url = self.page.vars.get("url")

        if not url:
            raise RedirectPageError("Redirect page is missing a url")

        status_code = self.page.vars.get("status_code", 302)
        return ResponseRedirect(url, status_code=status_code)


class PageAssetView(PageViewMixin, AssetView):
    def get_url_path(self):
        return self.page.get_url_path()

    def get_asset_path(self, path):
        return self.page.absolute_path

    def get_debug_asset_path(self, path):
        return self.page.absolute_path


class PageMarkdownView(PageViewMixin, View):
    def get(self):
        """Serve the markdown content without frontmatter."""
        markdown_content = self.page._frontmatter.content
        response = Response(markdown_content, content_type="text/plain; charset=utf-8")
        response.headers["Vary"] = (
            "Accept-Encoding"  # Set Vary header for proper caching
        )
        return response
