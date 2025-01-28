import os

import frontmatter

from plain.templates import Template
from plain.utils.functional import cached_property

from .markdown import render_markdown


class Page:
    def __init__(self, relative_path, absolute_path):
        self.relative_path = relative_path
        self.absolute_path = absolute_path

    @cached_property
    def _frontmatter(self):
        with open(self.absolute_path) as f:
            return frontmatter.load(f)

    @cached_property
    def vars(self):
        return self._frontmatter.metadata

    @cached_property
    def title(self):
        default_title = os.path.splitext(os.path.basename(self.relative_path))[0]
        return self.vars.get("title", default_title)

    @cached_property
    def content(self):
        # Strip the frontmatter
        content = self._frontmatter.content

        if not self.vars.get("render_plain", False):
            template = Template(os.path.join("pages", self.relative_path))
            content = template.render({})
            # Strip the frontmatter again, since it was in the template file itself
            _, content = frontmatter.parse(content)

        if self.is_markdown():
            content = render_markdown(content)

        return content

    def is_markdown(self):
        extension = os.path.splitext(self.absolute_path)[1]
        return extension == ".md"

    def is_template(self):
        return ".template." in os.path.basename(self.absolute_path)

    def is_asset(self):
        extension = os.path.splitext(self.absolute_path)[1]
        return extension.lower() in (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".svg",
            ".js",
            ".css",
            ".ico",
        )

    def is_redirect(self):
        extension = os.path.splitext(self.absolute_path)[1]
        return extension == ".redirect"

    def get_url_path(self) -> str | None:
        if self.is_template():
            return None

        if self.is_asset():
            return self.relative_path

        url_path = os.path.splitext(self.relative_path)[0]

        # If it's an index.html or something, the url is the parent dir
        if os.path.basename(url_path) == "index":
            url_path = os.path.dirname(url_path)

        return url_path + "/"  # With trailing slash

    def get_template_name(self):
        if template_name := self.vars.get("template_name"):
            return template_name

        return ""

    def get_view_class(self):
        from .views import PageAssetView, PageRedirectView, PageView

        if self.is_redirect():
            return PageRedirectView

        if self.is_asset():
            return PageAssetView

        return PageView
