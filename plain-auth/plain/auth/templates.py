from __future__ import annotations

from typing import TYPE_CHECKING, Any

from jinja2 import pass_context

from plain.templates import register_template_global

from .requests import get_request_user

if TYPE_CHECKING:
    from jinja2.runtime import Context


@register_template_global
@pass_context
def get_current_user(context: Context) -> Any | None:
    """Get the authenticated user for the current request."""
    request = context.get("request")
    assert request is not None, "No request in template context"
    return get_request_user(request)
