from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HttpMiddleware, Response
from plain.runtime import settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request


class HealthcheckMiddleware(HttpMiddleware):
    def __init__(self, get_response: Callable[[Request], Response]):
        super().__init__(get_response)
        self.healthcheck_path = settings.HEALTHCHECK_PATH

    def process_request(self, request: Request) -> Response:
        if self.healthcheck_path and request.path_info == self.healthcheck_path:
            return Response("ok", content_type="text/plain", status_code=200)

        return self.get_response(request)
