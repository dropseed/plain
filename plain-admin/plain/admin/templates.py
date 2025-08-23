from plain.runtime import settings
from plain.templates import register_template_extension, register_template_filter
from plain.templates.jinja.extensions import InclusionTagExtension

from .toolbar import Toolbar
from .views.registry import registry


@register_template_extension
class ToolbarExtension(InclusionTagExtension):
    tags = {"toolbar"}
    template_name = "toolbar/toolbar.html"

    def get_context(self, context, *args, **kwargs):
        context.vars["toolbar"] = Toolbar(request=context["request"])
        context.vars["app_name"] = settings.APP_NAME
        return context


@register_template_filter
def get_admin_model_detail_url(obj):
    return registry.get_model_detail_url(obj)
