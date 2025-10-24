from typing import Any

from plain.auth.requests import get_request_user
from plain.toolbar import ToolbarItem, register_toolbar_item

from .impersonate import get_request_impersonator
from .views.registry import registry


@register_toolbar_item
class AdminToolbarItem(ToolbarItem):
    name = "Admin"
    button_template_name = "admin/toolbar/button.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        # Add admin-specific context for the object if it exists
        if "object" in context:
            obj = context["object"]
            context["object_admin_url"] = registry.get_model_detail_url(obj)
            context["object_class_name"] = obj.__class__.__name__
        context["impersonator"] = get_request_impersonator(self.request)
        context["user"] = get_request_user(self.request)
        return context
