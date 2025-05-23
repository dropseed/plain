from functools import cached_property

from plain.assets.views import AssetView
from plain.http import Http404, ResponsePermanentRedirect, ResponseRedirect
from plain.views import TemplateView, View

from .exceptions import PageNotFoundError, RedirectPageError
from .registry import pages_registry


class PageViewMixin:
    @cached_property
    def page(self):
        url_name = self.request.resolver_match.url_name

        try:
            return pages_registry.get_page(url_name)
        except PageNotFoundError:
            raise Http404()


class PageView(PageViewMixin, TemplateView):
    template_name = "page.html"

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

        if self.page.vars.get("temporary", True):
            return ResponseRedirect(url)
        else:
            return ResponsePermanentRedirect(url)


class PageAssetView(PageViewMixin, AssetView):
    def get_url_path(self):
        return self.page.get_url_path()

    def get_asset_path(self, path):
        return self.page.absolute_path

    def get_debug_asset_path(self, path):
        return self.page.absolute_path
