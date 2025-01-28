from plain.assets.views import AssetView
from plain.http import Http404, ResponsePermanentRedirect, ResponseRedirect
from plain.utils.functional import cached_property
from plain.views import TemplateView, View

from .exceptions import PageNotFoundError, RedirectPageError
from .registry import registry


class PageViewMixin:
    @cached_property
    def page(self):
        # Passed manually by the kwargs in the path definition
        url_path = self.url_kwargs.get("url_path", "index")

        try:
            return registry.get_page(url_path)
        except PageNotFoundError:
            raise Http404()


class PageView(PageViewMixin, TemplateView):
    template_name = "page.html"

    def get_template_names(self) -> list[str]:
        """
        Allow for more specific user templates like
        markdown.html or html.html
        """
        return [self.page.get_template_name()] + super().get_template_names()

    def get_template_context(self):
        context = super().get_template_context()
        context["page"] = self.page
        self.page.set_template_context(context)  # Pass the standard context through
        return context


class PageRedirectView(PageViewMixin, View):
    def get(self):
        # Passed manually by the kwargs in the path definition
        url_path = self.url_kwargs.get("url_path", "index")

        url = self.page.vars.get("url")

        if not url:
            raise RedirectPageError(f"Redirect page {url_path} is missing a url")

        if self.page.vars.get("temporary", True):
            return ResponseRedirect(url)
        else:
            return ResponsePermanentRedirect(url)


class PageAssetView(PageViewMixin, AssetView):
    def get_url_path(self):
        return self.url_kwargs["url_path"]

    def get_asset_path(self, path):
        return self.page.absolute_path

    def get_debug_asset_path(self, path):
        return self.page.absolute_path
