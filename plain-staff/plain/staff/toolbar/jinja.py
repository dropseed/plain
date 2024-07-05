from plain.runtime import settings
from plain.templates.jinja.extensions import InclusionTagExtension
from plain.utils.module_loading import import_string


class ToolbarExtension(InclusionTagExtension):
    tags = {"toolbar"}
    template_name = "toolbar/toolbar.html"

    def get_context(self, context, *args, **kwargs):
        if isinstance(settings.TOOLBAR_CLASS, str):
            cls = import_string(settings.TOOLBAR_CLASS)
        else:
            cls = settings.TOOLBAR_CLASS
        context.vars["toolbar"] = cls(request=context.get("request"))
        return context


extensions = [
    ToolbarExtension,
]
