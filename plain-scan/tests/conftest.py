from __future__ import annotations

from collections.abc import Mapping, Sequence

import requests
from requests.cookies import RequestsCookieJar
from requests.structures import CaseInsensitiveDict


def make_response(
    *,
    headers: Mapping[str, str] | None = None,
    status_code: int = 200,
    url: str = "https://example.com/",
    history: Sequence[requests.Response] = (),
) -> requests.Response:
    """Build a synthetic ``requests.Response`` for driving audits offline."""
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.headers = CaseInsensitiveDict(headers or {})
    response.history = list(history)
    response.cookies = RequestsCookieJar()
    return response
