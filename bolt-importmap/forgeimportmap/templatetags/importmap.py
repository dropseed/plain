import json

from django import template
from django.conf import settings

from ..core import Importmap

register = template.Library()


@register.inclusion_tag("importmap/scripts.html")
def importmap_scripts():
    importmap = Importmap()
    importmap.load()

    if settings.DEBUG:
        return {"importmap": json.dumps(importmap.map_dev, indent=2, sort_keys=True)}
    else:
        return {"importmap": json.dumps(importmap.map, sort_keys=True)}
