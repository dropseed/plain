from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from jinja2.runtime import Context

from plain.runtime import settings
from plain.templates import Template
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

        if get_request_user:
            if user := get_request_user(self.request):
                return getattr(user, "is_admin", False)

        return False

    def get_items(self) -> list[ToolbarItem]:
        items = [item(self.context) for item in registry.get_items()]
        enabled = [item for item in items if item.is_enabled()]
        return sorted(enabled, key=lambda item: item.name)


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

    def is_enabled(self) -> bool:
        """Return whether this toolbar item should be displayed."""
        return True


@register_toolbar_item
class _ExceptionToolbarItem(ToolbarItem):
    name = "Exception"
    panel_template_name = "toolbar/exception.html"
    button_template_name = "toolbar/exception_button.html"

    def __init__(self, context: Context) -> None:
        super().__init__(context)
        exception = sys.exception()
        if exception:
            from .exceptions import ExceptionContext

            self.exception_context: ExceptionContext | None = ExceptionContext(
                exception
            )
        else:
            self.exception_context = None

    def is_enabled(self) -> bool:
        return self.exception_context is not None

    def get_template_context(self) -> dict[str, Any]:
        ctx = super().get_template_context()
        ctx["exception_context"] = self.exception_context
        return ctx


@register_toolbar_item
class _RequestToolbarItem(ToolbarItem):
    name = "Request"
    panel_template_name = "toolbar/request.html"
