"""Thin HTTP client for the Plain Cloud API.

Wraps httpx with the bearer token from credentials and surfaces non-2xx
responses as `APIError` with the server's message when available.
"""

from __future__ import annotations

from typing import Any

import click
import httpx

from .credentials import Credentials


class APIError(click.ClickException):
    """Non-2xx response from the API. Click prints the message in red and exits 1."""

    exit_code = 1

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code

    def show(self, file: Any = None) -> None:
        click.secho(self.message, fg="red", err=True)


class Client:
    def __init__(
        self,
        creds: Credentials,
        *,
        transport: httpx.BaseTransport | None = None,  # test seam for MockTransport
    ) -> None:
        self._client = httpx.Client(
            base_url=creds.api_url.rstrip("/") + "/api",
            headers={
                "Authorization": f"Bearer {creds.token}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0),
            # Follow redirects so a trailing-slash mismatch (the API serves
            # /me, not /me/) or a server-side route move resolves to the real
            # response instead of an empty 3xx body that parses to None.
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: Any) -> None:
        self._client.close()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def raw_request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send a request and return the raw response without raising on
        non-2xx. Used by the `api` escape-hatch subcommand so the user
        sees the actual response body and status code from the server.
        """
        if not path.startswith("/"):
            path = "/" + path
        return self._client.request(method, path, **kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.raw_request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                payload = response.json()
                message = (
                    payload.get("error") or payload.get("message") or response.text
                )
            except ValueError:
                message = response.text or response.reason_phrase
            raise APIError(response.status_code, message)
        if not response.content:
            return None
        return response.json()
