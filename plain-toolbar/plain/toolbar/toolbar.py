import sys
import traceback

from plain.runtime import settings
from plain.templates import Template
from plain.urls.exceptions import Resolver404
from plain.utils.safestring import mark_safe

from .registry import register_toolbar_item, registry


class Toolbar:
    def __init__(self, context):
        self.context = context
        self.request = context["request"]
        self.version = settings.APP_VERSION

    def should_render(self):
        if settings.DEBUG:
            return True

        if impersonator := getattr(self.request, "impersonator", None):
            return getattr(impersonator, "is_admin", False)

        if user := getattr(self.request, "user", None):
            return getattr(user, "is_admin", False)

        return False

    def request_exception(self):
        # We can capture the exception currently being handled here, if any.
        exception = sys.exception()

        if exception and not isinstance(exception, Resolver404):
            exception._traceback_string = "".join(
                traceback.format_tb(exception.__traceback__)
            )
            return exception

    def get_items(self):
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

    def __init__(self, context):
        self.context = context
        self.request = context["request"]

    def get_template_context(self):
        context = dict(self.context)
        context["panel"] = self
        return context

    def render_panel(self):
        template = Template(self.panel_template_name)
        context = self.get_template_context()
        return mark_safe(template.render(context))

    def render_button(self):
        """Render the toolbar button for the minimized state."""
        template = Template(self.button_template_name)
        context = self.get_template_context()
        return mark_safe(template.render(context))


class _ExceptionToolbarItem(ToolbarItem):
    name = "Exception"
    panel_template_name = "toolbar/exception.html"
    button_template_name = "toolbar/exception_button.html"

    def __init__(self, context, exception):
        super().__init__(context)
        self.exception = exception

    def get_template_context(self):
        context = super().get_template_context()
        context["exception"] = self.exception
        return context


@register_toolbar_item
class _RequestToolbarItem(ToolbarItem):
    name = "Request"
    panel_template_name = "toolbar/request.html"
