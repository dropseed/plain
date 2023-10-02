from bolt.jinja.extensions import InclusionTagExtension
from bolt.runtime import settings
from bolt.utils.module_loading import import_string


class ToolbarExtension(InclusionTagExtension):
    tags = {"toolbar"}
    template_name = "toolbar/toolbar.html"

    def get_context(self, context, *args, outer_class="", inner_class="", **kwargs):
        if isinstance(settings.TOOLBAR_CLASS, str):
            cls = import_string(settings.TOOLBAR_CLASS)
        else:
            cls = settings.TOOLBAR_CLASS
        context.vars["toolbar"] = cls(request=context.get("request"))
        context.vars["toolbar_outer_class"] = outer_class
        context.vars["toolbar_inner_class"] = inner_class
        return context


extensions = [
    ToolbarExtension,
]
