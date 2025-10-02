from jinja2 import pass_context

from plain.templates import register_template_global

from .requests import get_request_user


@register_template_global
@pass_context
def get_current_user(context):
    """Get the authenticated user for the current request."""
    request = context.get("request")
    assert request is not None, "No request in template context"
    return get_request_user(request)
