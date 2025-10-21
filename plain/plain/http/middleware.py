from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.http import Request, Response


class HttpMiddleware(ABC):
    """
    Abstract base class for HTTP middleware.

    Subclasses must implement process_request() to handle the request/response cycle.

    Example:
        class MyMiddleware(HttpMiddleware):
            def process_request(self, request: Request) -> Response:
                # Pre-processing
                response = self.get_response(request)
                # Post-processing
                return response
    """

    def __init__(self, get_response: Callable[[Request], Response]):
        self.get_response = get_response

    @abstractmethod
    def process_request(self, request: Request) -> Response:
        """Process the request and return a response. Must be implemented by subclasses."""
        ...
