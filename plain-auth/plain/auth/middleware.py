from __future__ import annotations

from plain.http import HttpMiddleware, Request, Response

from .requests import get_request_user

__all__ = ["AuthMiddleware"]


class AuthMiddleware(HttpMiddleware):
    def before_request(self, request: Request) -> Response | None:
        get_request_user(request)
        return None
