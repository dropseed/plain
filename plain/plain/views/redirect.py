from plain.http import ResponseRedirect
from plain.urls import reverse

from .base import View


class RedirectView(View):
    """Provide a redirect on any GET request."""

    status_code = 302
    url: str | None = None
    url_name: str | None = None
    preserve_query_params = False

    def __init__(
        self,
        url: str | None = None,
        status_code: int | None = None,
        url_name: str | None = None,
        preserve_query_params: bool | None = None,
    ) -> None:
        # Allow attributes to be set in RedirectView.as_view(url="...", status_code=301, etc.)
        self.url = url or self.url
        self.status_code = status_code if status_code is not None else self.status_code
        self.url_name = url_name or self.url_name
        self.preserve_query_params = (
            preserve_query_params
            if preserve_query_params is not None
            else self.preserve_query_params
        )

    def get_redirect_url(self) -> str:
        """
        Return the URL redirect to. Keyword arguments from the URL pattern
        match generating the redirect request are provided as kwargs to this
        method.
        """
        if self.url:
            url = self.url % self.url_kwargs
        elif self.url_name:
            url = reverse(self.url_name, *self.url_args, **self.url_kwargs)
        else:
            raise ValueError("RedirectView requires either url or url_name to be set")

        args = self.request.meta.get("QUERY_STRING", "")
        if args and self.preserve_query_params:
            url = f"{url}?{args}"
        return url

    def get(self) -> ResponseRedirect:
        url = self.get_redirect_url()
        return ResponseRedirect(url, status_code=self.status_code)

    def head(self) -> ResponseRedirect:
        return self.get()

    def post(self) -> ResponseRedirect:
        return self.get()

    def options(self) -> ResponseRedirect:
        return self.get()

    def delete(self) -> ResponseRedirect:
        return self.get()

    def put(self) -> ResponseRedirect:
        return self.get()

    def patch(self) -> ResponseRedirect:
        return self.get()
