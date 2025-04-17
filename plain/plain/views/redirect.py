import logging

from plain.http import (
    ResponseGone,
    ResponsePermanentRedirect,
    ResponseRedirect,
)
from plain.urls import reverse

from .base import View

logger = logging.getLogger("plain.request")


class RedirectView(View):
    """Provide a redirect on any GET request."""

    permanent = False
    url: str | None = None
    pattern_name: str | None = None
    query_string = False

    def __init__(self, url=None, permanent=None):
        # Allow url and permanent to be set in RedirectView.as_view(url="...", permanent=True)
        self.url = url or self.url
        self.permanent = permanent if permanent is not None else self.permanent

    def get_redirect_url(self):
        """
        Return the URL redirect to. Keyword arguments from the URL pattern
        match generating the redirect request are provided as kwargs to this
        method.
        """
        if self.url:
            url = self.url % self.url_kwargs
        elif self.pattern_name:
            url = reverse(self.pattern_name, *self.url_args, **self.url_kwargs)
        else:
            return None

        args = self.request.meta.get("QUERY_STRING", "")
        if args and self.query_string:
            url = f"{url}?{args}"
        return url

    def get(self):
        url = self.get_redirect_url()
        if url:
            if self.permanent:
                return ResponsePermanentRedirect(url)
            else:
                return ResponseRedirect(url)
        else:
            logger.warning(
                "Gone: %s",
                self.request.path,
                extra={"status_code": 410, "request": self.request},
            )
            return ResponseGone()

    def head(self):
        return self.get()

    def post(self):
        return self.get()

    def options(self):
        return self.get()

    def delete(self):
        return self.get()

    def put(self):
        return self.get()

    def patch(self):
        return self.get()
