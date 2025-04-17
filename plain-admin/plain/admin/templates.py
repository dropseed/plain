from plain.runtime import settings
from plain.templates import register_template_extension, register_template_filter
from plain.templates.jinja.extensions import InclusionTagExtension
from plain.utils.module_loading import import_string

from .views.registry import registry


@register_template_extension
class ToolbarExtension(InclusionTagExtension):
    tags = {"toolbar"}
    template_name = "toolbar/toolbar.html"

    def get_context(self, context, *args, **kwargs):
        if isinstance(settings.ADMIN_TOOLBAR_CLASS, str):
            cls = import_string(settings.ADMIN_TOOLBAR_CLASS)
        else:
            cls = settings.ADMIN_TOOLBAR_CLASS
        context.vars["toolbar"] = cls(request=context["request"])
        return context


@register_template_filter
def get_admin_model_detail_url(obj):
    return registry.get_model_detail_url(obj)
