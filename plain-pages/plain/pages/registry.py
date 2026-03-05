from __future__ import annotations

import os

from plain.runtime import settings
from plain.urls import URLPattern, reverse
from plain.urls import path as url_path

from .exceptions import PageNotFoundError
from .pages import Page


class PagesRegistry:
    """
    The registry loads up all the pages at once, so we only have to do a
    dict key lookup at runtime to get a page.
    """

    def __init__(self):
        self._url_name_mappings = {}  # url_name -> relative_path
        self._path_mappings = {}  # relative_path -> absolute_path
        self._companions = {}  # html_relative_path -> md_relative_path

    def get_page_urls(self) -> list[URLPattern]:
        """
        Generate a list of real urls based on the files that exist.
        This way, you get a concrete url reversingerror if you try
        to refer to a page/url that isn't going to work.
        """
        companion_md_paths = set(self._companions.values())
        paths = []

        for relative_path in self._path_mappings:
            if relative_path in companion_md_paths:
                continue

            page = self.get_page_from_path(relative_path)
            paths.extend(page.get_urls())

        # Add .md URLs for companion markdown files
        if settings.PAGES_SERVE_MARKDOWN and self._companions:
            from .views import PageMarkdownView  # circular

            for html_path, md_path in self._companions.items():
                html_page = self.get_page_from_path(html_path)
                url_name = html_page.get_url_name()
                if url_name:
                    md_url_name = f"{url_name}-md"
                    self._url_name_mappings[md_url_name] = md_path
                    paths.append(
                        url_path(
                            md_path,
                            PageMarkdownView,
                            name=md_url_name,
                        )
                    )

        return paths

    def discover_pages(self, pages_dir: str) -> None:
        # Collect all files first so we can detect .md/.html pairs
        candidates = {}
        for root, _, files in os.walk(pages_dir, followlinks=True):
            for file in files:
                relative_path = str(
                    os.path.relpath(os.path.join(root, file), pages_dir)
                )
                absolute_path = str(os.path.join(root, file))
                candidates[relative_path] = absolute_path

        # First pass: register all non-.md files so _path_mappings
        # reflects which HTML pages are actually routable
        for relative_path, absolute_path in candidates.items():
            if os.path.splitext(relative_path)[1] != ".md":
                self._register_page(relative_path, absolute_path)

        # Second pass: register .md files, detecting companions
        # against _path_mappings (not candidates) to skip non-routable
        # HTML like .template.html files
        for relative_path, absolute_path in candidates.items():
            if os.path.splitext(relative_path)[1] != ".md":
                continue

            stem = os.path.splitext(relative_path)[0]
            html_path = stem + ".html"

            if html_path in self._path_mappings:
                # Companion .md — paired with a routable HTML page
                self._path_mappings[relative_path] = absolute_path
                self._companions[html_path] = relative_path
            else:
                self._register_page(relative_path, absolute_path)

    def _register_page(self, relative_path: str, absolute_path: str) -> None:
        """Register a single page in the registry."""
        page = Page(relative_path=relative_path, absolute_path=absolute_path)
        urls = page.get_urls()

        # Some pages don't get any urls (like templates)
        if not urls:
            return

        self._path_mappings[relative_path] = absolute_path

        for url_path_obj in urls:
            url_name = url_path_obj.name
            self._url_name_mappings[url_name] = relative_path

    def get_page_from_name(self, url_name: str) -> Page:
        """Get a page by its URL name."""
        try:
            relative_path = self._url_name_mappings[url_name]
            return self.get_page_from_path(relative_path)
        except KeyError:
            raise PageNotFoundError(f"Could not find a page for URL name {url_name}")

    def get_page_from_path(self, relative_path: str) -> Page:
        """Get a page by its relative file path."""
        try:
            absolute_path = self._path_mappings[relative_path]
            # Instantiate the page here, so we don't store a ton of cached data over time
            # as we render all the pages
            return Page(relative_path=relative_path, absolute_path=absolute_path)
        except KeyError:
            raise PageNotFoundError(f"Could not find a page for path {relative_path}")

    def get_markdown_companion(self, url_name: str) -> Page | None:
        """Look up the paired markdown Page for a given url_name."""
        try:
            html_path = self._url_name_mappings[url_name]
        except KeyError:
            return None
        md_path = self._companions.get(html_path)
        if md_path:
            return self.get_page_from_path(md_path)
        return None

    def get_markdown_url(self, url_name: str) -> str | None:
        """Get the markdown URL for a page, whether standalone .md or paired with .html."""
        md_url_name = f"{url_name}-md"
        if md_url_name in self._url_name_mappings:
            return reverse(f"pages:{md_url_name}")
        return None


pages_registry = PagesRegistry()
