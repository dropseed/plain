import os
from functools import cached_property

import frontmatter

from plain.runtime import settings
from plain.templates import Template
from plain.urls import path, reverse

from .markdown import render_markdown


class PageRenderError(Exception):
    pass


class Page:
    def __init__(self, relative_path, absolute_path):
        self.relative_path = relative_path
        self.absolute_path = absolute_path
        self._template_context = {}

    def set_template_context(self, context):
        self._template_context = context

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

            try:
                content = template.render(self._template_context)
            except Exception as e:
                # Throw our own error so we don't get shadowed by the Jinja error
                raise PageRenderError(f"Error rendering page {self.relative_path}: {e}")

            # Strip the frontmatter again, since it was in the template file itself
            _, content = frontmatter.parse(content)

        if self.is_markdown():
            content = render_markdown(content, current_page_path=self.relative_path)

        return content

    def is_markdown(self):
        extension = os.path.splitext(self.absolute_path)[1]
        return extension == ".md"

    def is_template(self):
        return ".template." in os.path.basename(self.absolute_path)

    def is_asset(self):
        extension = os.path.splitext(self.absolute_path)[1]
        # Anything that we don't specifically recognize for pages
        # gets treated as an asset
        return extension.lower() not in (
            ".html",
            ".md",
            ".redirect",
        )

    def is_redirect(self):
        extension = os.path.splitext(self.absolute_path)[1]
        return extension == ".redirect"

    def get_template_name(self):
        if template_name := self.vars.get("template_name"):
            return template_name

        return ""

    def get_url_path(self):
        """Generate the primary URL path for this page."""
        if self.is_template():
            return None

        if self.is_asset():
            return self.relative_path

        url_path = os.path.splitext(self.relative_path)[0]

        # If it's an index.html or something, the url is the parent dir
        if os.path.basename(url_path) == "index":
            url_path = os.path.dirname(url_path)

        # The root url should stay an empty string
        if not url_path:
            return ""

        # Everything else should get a trailing slash
        return url_path + "/"

    def get_url_name(self):
        """Generate the URL name from the URL path."""
        url_path = self.get_url_path()
        if url_path is None:
            return None

        if not url_path:
            return "index"

        return url_path.rstrip("/")

    def get_view_class(self):
        """Get the appropriate view class for this page."""
        from .views import PageAssetView, PageRedirectView, PageView

        if self.is_redirect():
            return PageRedirectView

        if self.is_asset():
            return PageAssetView

        return PageView

    def get_markdown_url(self):
        """Get the markdown URL for this page if it exists."""
        if not self.is_markdown():
            return None

        if not settings.PAGES_SERVE_MARKDOWN:
            return None

        url_name = self.get_url_name()
        if not url_name:
            return None

        return reverse(f"pages:{url_name}-md")

    def get_urls(self):
        """Get all URL path objects for this page."""
        urls = []

        # Generate primary URL
        url_path = self.get_url_path()
        url_name = self.get_url_name()
        view_class = self.get_view_class()

        if url_path is not None and url_name is not None:
            urls.append(
                path(
                    url_path,
                    view_class,
                    name=url_name,
                )
            )

            # For markdown files, optionally add .md URL
            if self.is_markdown() and settings.PAGES_SERVE_MARKDOWN:
                from .views import PageMarkdownView

                urls.append(
                    path(
                        self.relative_path,
                        PageMarkdownView,
                        name=f"{url_name}-md",
                    )
                )

        return urls
