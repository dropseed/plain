from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension

from .toolbar import Toolbar


@register_template_extension
class ToolbarExtension(InclusionTagExtension):
    tags = {"toolbar"}
    template_name = "toolbar/toolbar.html"

    def get_context(self, context, *args, **kwargs):
        context.vars["toolbar"] = Toolbar(context=context)
        return context
