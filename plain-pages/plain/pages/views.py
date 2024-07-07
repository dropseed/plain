from plain.http import Http404, ResponsePermanentRedirect, ResponseRedirect
from plain.utils.functional import cached_property
from plain.views import TemplateView

from .exceptions import PageNotFoundError, RedirectPageError
from .registry import registry


class PageView(TemplateView):
    template_name = "page.html"

    @cached_property
    def page(self):
        # Passed manually by the kwargs in the path definition
        url_path = self.url_kwargs.get("url_path", "index")

        try:
            return registry.get_page(url_path)
        except PageNotFoundError:
            raise Http404()

    def get_template_names(self) -> list[str]:
        """
        Allow for more specific user templates like
        markdown.html or html.html
        """
        return [self.page.get_template_name()] + super().get_template_names()

    def get_template_context(self):
        context = super().get_template_context()
        context["page"] = self.page
        return context

    def get(self):
        if self.page.content_type == "redirect":
            url = self.page.vars.get("url")

            if not url:
                raise RedirectPageError(
                    f"Redirect page {self.page.url_path} is missing a url"
                )

            if self.page.vars.get("temporary", True):
                return ResponseRedirect(url)
            else:
                return ResponsePermanentRedirect(url)

        return super().get()
