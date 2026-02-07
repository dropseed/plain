from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from plain.views import View

from .requests import get_request_session

if TYPE_CHECKING:
    from .core import SessionStore

__all__ = ["SessionView"]


class SessionView(View):
    """View with session access."""

    @cached_property
    def session(self) -> SessionStore:
        """Get the session for this request."""
        return get_request_session(self.request)

    def get_template_context(self) -> dict:
        """Add session to template context."""
        context = super().get_template_context()  # type: ignore[misc]
        context["session"] = self.session
        return context
