import os

from .exceptions import PageNotFoundError
from .pages import Page


class PagesRegistry:
    """
    The registry loads up all the pages at once, so we only have to do a
    dict key lookup at runtime to get a page.
    """

    def __init__(self):
        # url path -> file path
        self.registered_pages = {}

    def register_page(self, url_path, relative_path, absolute_path):
        self.registered_pages[url_path] = (url_path, relative_path, absolute_path)

    def url_paths(self):
        return self.registered_pages.keys()

    def discover_pages(self, pages_dir):
        for root, dirs, files in os.walk(pages_dir):
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), pages_dir)
                url_path = os.path.splitext(relative_path)[0]
                absolute_path = os.path.join(root, file)

                if os.path.basename(url_path) == "index":
                    url_path = os.path.dirname(url_path)

                self.register_page(url_path, relative_path, absolute_path)

    def get_page(self, url_path):
        try:
            url_path, relative_path, absolute_path = self.registered_pages[url_path]
            # Instantiate the page here, so we don't store a ton of cached data over time
            # as we render all the pages
            return Page(url_path, relative_path, absolute_path)
        except KeyError:
            raise PageNotFoundError(f"Could not find a page for {url_path}")


registry = PagesRegistry()
