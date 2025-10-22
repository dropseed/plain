from __future__ import annotations

import sys
import traceback
from typing import TYPE_CHECKING, Any

from jinja2.runtime import Context

from plain.runtime import settings
from plain.templates import Template
from plain.urls.exceptions import Resolver404
from plain.utils.safestring import SafeString, mark_safe

from .registry import register_toolbar_item, registry

if TYPE_CHECKING:
    from plain.http import Request

try:
    from plain.auth import get_request_user
except ImportError:
    get_request_user: Any = None

try:
    from plain.admin.impersonate import get_request_impersonator
except ImportError:
    get_request_impersonator: Any = None


class Toolbar:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.request: Request = context["request"]
        self.version: str = settings.VERSION

    def should_render(self) -> bool:
        if settings.DEBUG:
            return True

        if get_request_impersonator:
            if impersonator := get_request_impersonator(self.request):
                return getattr(impersonator, "is_admin", False)

        user = get_request_user(self.request) if get_request_user else None
        if user:
            return getattr(user, "is_admin", False)

        return False

    def request_exception(self) -> BaseException | None:
        # We can capture the exception currently being handled here, if any.
        exception = sys.exception()

        if exception and not isinstance(exception, Resolver404):
            # Add a custom attribute to the exception for template rendering
            exception._traceback_string = "".join(  # type: ignore[attr-defined]
                traceback.format_tb(exception.__traceback__)
            )
            return exception

        return None

    def get_items(self) -> list[ToolbarItem]:
        items = [item(self.context) for item in registry.get_items()]

        if self.request_exception():
            exception = self.request_exception()
            items = [
                _ExceptionToolbarItem(self.context, exception),
            ] + items

        return items


class ToolbarItem:
    name: str = ""
    panel_template_name: str = ""
    button_template_name: str = ""

    def __init__(self, context: Context) -> None:
        self.context = context
        self.request: Request = context["request"]

    def get_template_context(self) -> dict[str, Any]:
        context = dict(self.context)
        context["panel"] = self
        return context

    def render_panel(self) -> SafeString:
        template = Template(self.panel_template_name)
        context = self.get_template_context()
        return mark_safe(template.render(context))

    def render_button(self) -> SafeString:
        """Render the toolbar button for the minimized state."""
        template = Template(self.button_template_name)
        context = self.get_template_context()
        return mark_safe(template.render(context))


class _ExceptionToolbarItem(ToolbarItem):
    name = "Exception"
    panel_template_name = "toolbar/exception.html"
    button_template_name = "toolbar/exception_button.html"

    def __init__(self, context: Context, exception: BaseException | None) -> None:
        super().__init__(context)
        self.exception = exception

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["exception"] = self.exception
        return context


@register_toolbar_item
class _RequestToolbarItem(ToolbarItem):
    name = "Request"
    panel_template_name = "toolbar/request.html"
