from bolt.jinja.extensions import InclusionTagExtension
from bolt.runtime import settings
from bolt.staticfiles.finders import APP_STATIC_DIR


class TailwindCSSExtension(InclusionTagExtension):
    tags = {"tailwind_css"}
    template_name = "tailwind/css.html"

    def get_context(self, context, *args, **kwargs):
        tailwind_static_path = str(
            settings.TAILWIND_DIST_PATH.relative_to(APP_STATIC_DIR)
        )
        return {"tailwind_static_path": tailwind_static_path}


extensions = [TailwindCSSExtension]
