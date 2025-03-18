import os

from plain.internal import internalcode
from plain.urls import path

from .exceptions import PageNotFoundError
from .pages import Page


@internalcode
class PagesRegistry:
    """
    The registry loads up all the pages at once, so we only have to do a
    dict key lookup at runtime to get a page.
    """

    def __init__(self):
        # url path -> file path
        self.registered_pages = {}

    def get_page_urls(self):
        """
        Generate a list of real urls based on the files that exist.
        This way, you get a concrete url reversingerror if you try
        to refer to a page/url that isn't going to work.
        """
        paths = []

        for url_name in self.registered_pages.keys():
            page = self.get_page(url_name)
            url = page.get_url_path()
            view_class = page.get_view_class()

            paths.append(
                path(
                    url,
                    view_class,
                    name=url_name,
                )
            )

        return paths

    def discover_pages(self, pages_dir):
        for root, _, files in os.walk(pages_dir):
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), pages_dir)
                absolute_path = os.path.join(root, file)

                page_args = (relative_path, absolute_path)
                url_name = Page(*page_args).get_url_name()

                # Some pages don't get a url (like templates)
                if url_name is None:
                    continue

                self.registered_pages[url_name] = page_args

    def get_page(self, url_name):
        try:
            page_args = self.registered_pages[url_name]
            # Instantiate the page here, so we don't store a ton of cached data over time
            # as we render all the pages
            return Page(*page_args)
        except KeyError:
            raise PageNotFoundError(f"Could not find a page for {url_name}")


pages_registry = PagesRegistry()
