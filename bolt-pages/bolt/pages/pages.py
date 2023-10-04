import os

import frontmatter
import pycmarkgfm

from bolt.jinja import environment
from bolt.runtime import settings
from bolt.utils.functional import cached_property


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
    def html_content(self):
        content = self._frontmatter.content

        if self.content_type == "markdown":
            # option to use jinja first? or yes by default? or by file extension?
            content = pycmarkgfm.markdown_to_html(
                content,
                options=settings.PYCMARKGFM_OPTIONS,
                extensions=settings.PYCMARKGFM_EXTENSIONS,
            )
        elif self.content_type == "html":
            content = environment.from_string(content).render()

        return content

    @property
    def content_type(self):
        extension = os.path.splitext(self.absolute_path)[1]
        if extension == ".md":
            return "markdown"

        if extension == ".html":
            return "html"

        return extension.lstrip(".")
