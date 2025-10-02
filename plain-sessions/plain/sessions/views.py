from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

from .requests import get_request_session

if TYPE_CHECKING:
    from plain.http import Request

    from .core import SessionStore


class SessionViewMixin:
    """Mixin that adds session access to views."""

    request: Request

    @cached_property
    def session(self) -> SessionStore:
        """Get the session for this request."""
        return get_request_session(self.request)

    def get_template_context(self) -> dict:
        """Add session to template context."""
        context = super().get_template_context()  # type: ignore
        context["session"] = self.session
        return context
