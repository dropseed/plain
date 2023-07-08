from bolt.jinja.extensions import InclusionTagExtension
from django.conf import settings
from .core import Importmap
import json

class ImportmapScriptsExtension(InclusionTagExtension):
    tags = {"importmap_scripts"}
    template_name = "importmap/scripts.html"

    def get_context(self, context, *args, **kwargs):
        importmap = Importmap()
        importmap.load()

        if settings.DEBUG:
            return {"importmap": json.dumps(importmap.map_dev, indent=2, sort_keys=True)}
        else:
            return {"importmap": json.dumps(importmap.map, sort_keys=True)}


extensions = [
    ImportmapScriptsExtension,
]
