from bolt.http import Http404
from bolt.utils.functional import cached_property
from bolt.views import TemplateView

from .exceptions import PageNotFoundError
from .registry import registry


class PageView(TemplateView):
    template_name = "pages/page.html"

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
        pages/markdown.html or pages/html.html
        """
        content_type_template_name = f"pages/{self.page.content_type}.html"
        return [content_type_template_name] + super().get_template_names()

    def get_context(self):
        context = super().get_context()
        context["page"] = self.page
        return context
