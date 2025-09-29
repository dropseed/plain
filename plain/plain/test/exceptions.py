from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.http import Response


class RedirectCycleError(Exception):
    """The test client has been asked to follow a redirect loop."""

    def __init__(self, message: str, last_response: Response) -> None:
        super().__init__(message)
        self.last_response = last_response
        self.redirect_chain: list[tuple[str, int]] = last_response.redirect_chain  # type: ignore[attr-defined]
