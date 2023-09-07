from bolt.jinja.extensions import InclusionTagExtension
from bolt.runtime import settings
from bolt.utils.module_loading import import_string


class StaffToolbarExtension(InclusionTagExtension):
    tags = {"stafftoolbar"}
    template_name = "stafftoolbar/stafftoolbar.html"

    def get_context(self, context, *args, outer_class="", inner_class="", **kwargs):
        if isinstance(settings.STAFFTOOLBAR_CLASS, str):
            cls = import_string(settings.STAFFTOOLBAR_CLASS)
        else:
            cls = settings.STAFFTOOLBAR_CLASS
        context.vars["stafftoolbar"] = cls(request=context.get("request"))
        context.vars["stafftoolbar_outer_class"] = outer_class
        context.vars["stafftoolbar_inner_class"] = inner_class
        return context


extensions = [
    StaffToolbarExtension,
]
