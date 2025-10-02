from __future__ import annotations

from typing import Any

from jinja2 import pass_context

from plain.templates import register_template_global

from .core import SessionStore
from .requests import get_request_session


@register_template_global
@pass_context
def get_current_session(context: dict[str, Any]) -> SessionStore:
    """Get the session for the current request."""
    request = context.get("request")
    assert request is not None, "No request in template context"
    return get_request_session(request)
