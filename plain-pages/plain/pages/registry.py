import os

from plain.internal import internalcode

from .exceptions import PageNotFoundError
from .pages import Page


@internalcode
class PagesRegistry:
    """
    The registry loads up all the pages at once, so we only have to do a
    dict key lookup at runtime to get a page.
    """

    def __init__(self):
        self._url_name_mappings = {}  # url_name -> relative_path
        self._path_mappings = {}  # relative_path -> absolute_path

    def get_page_urls(self):
        """
        Generate a list of real urls based on the files that exist.
        This way, you get a concrete url reversingerror if you try
        to refer to a page/url that isn't going to work.
        """
        paths = []

        for relative_path in self._path_mappings.keys():
            page = self.get_page_from_path(relative_path)

            # Get all URL path objects from the page
            paths.extend(page.get_urls())

        return paths

    def discover_pages(self, pages_dir):
        for root, _, files in os.walk(pages_dir, followlinks=True):
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), pages_dir)
                absolute_path = os.path.join(root, file)

                page = Page(relative_path=relative_path, absolute_path=absolute_path)
                urls = page.get_urls()

                # Some pages don't get any urls (like templates)
                if not urls:
                    continue

                # Register the page by its file path
                self._path_mappings[relative_path] = absolute_path

                # Register all URL names to point back to this file path
                for url_path_obj in urls:
                    url_name = url_path_obj.name
                    self._url_name_mappings[url_name] = relative_path

    def get_page_from_name(self, url_name):
        """Get a page by its URL name."""
        try:
            relative_path = self._url_name_mappings[url_name]
            return self.get_page_from_path(relative_path)
        except KeyError:
            raise PageNotFoundError(f"Could not find a page for URL name {url_name}")

    def get_page_from_path(self, relative_path):
        """Get a page by its relative file path."""
        try:
            absolute_path = self._path_mappings[relative_path]
            # Instantiate the page here, so we don't store a ton of cached data over time
            # as we render all the pages
            return Page(relative_path=relative_path, absolute_path=absolute_path)
        except KeyError:
            raise PageNotFoundError(f"Could not find a page for path {relative_path}")


pages_registry = PagesRegistry()
