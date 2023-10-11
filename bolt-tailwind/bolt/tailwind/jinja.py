from bolt.assets.finders import APP_ASSETS_DIR
from bolt.jinja.extensions import InclusionTagExtension
from bolt.runtime import settings


class TailwindCSSExtension(InclusionTagExtension):
    tags = {"tailwind_css"}
    template_name = "tailwind/css.html"

    def get_context(self, context, *args, **kwargs):
        tailwind_css_path = str(settings.TAILWIND_DIST_PATH.relative_to(APP_ASSETS_DIR))
        return {"tailwind_css_path": tailwind_css_path}


extensions = [TailwindCSSExtension]