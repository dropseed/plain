import os

import frontmatter

from plain.templates import Template
from plain.utils.functional import cached_property

from .markdown import render_markdown


class Page:
    def __init__(self, url_path, relative_path, absolute_path):
        self.url_path = url_path
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

        if self.content_type == "markdown":
            content = render_markdown(content)

        return content

    @property
    def content_type(self):
        extension = os.path.splitext(self.absolute_path)[1]

        # Explicitly define the known content types that we intend to handle
        # (others will still pass through)
        if extension == ".md":
            return "markdown"

        if extension == ".html":
            return "html"

        if extension == ".redirect":
            return "redirect"

        return extension.lstrip(".")

    def get_template_name(self):
        if template_name := self.vars.get("template_name"):
            return template_name

        return f"{self.content_type}.html"
