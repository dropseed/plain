from plain.assets.finders import APP_ASSETS_DIR
from plain.runtime import settings
from plain.templates.jinja.extensions import InclusionTagExtension


class TailwindCSSExtension(InclusionTagExtension):
    tags = {"tailwind_css"}
    template_name = "tailwind/css.html"

    def get_context(self, context, *args, **kwargs):
        tailwind_css_path = str(settings.TAILWIND_DIST_PATH.relative_to(APP_ASSETS_DIR))
        return {"tailwind_css_path": tailwind_css_path}


extensions = [TailwindCSSExtension]
