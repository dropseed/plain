import json

from plain.runtime import settings
from plain.templates import register_template_extension
from plain.templates.jinja.extensions import InclusionTagExtension

from .core import Importmap


@register_template_extension
class ImportmapJSExtension(InclusionTagExtension):
    tags = {"importmap_js"}
    template_name = "importmap/js.html"

    def get_context(self, context, *args, **kwargs):
        importmap = Importmap()
        importmap.load()

        if settings.DEBUG:
            return {
                "importmap": json.dumps(importmap.map_dev, indent=2, sort_keys=True)
            }
        else:
            return {"importmap": json.dumps(importmap.map, sort_keys=True)}
