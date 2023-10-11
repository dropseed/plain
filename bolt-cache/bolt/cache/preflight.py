from bolt.preflight import Error, register
from bolt.runtime import settings

from .constants import DEFAULT_CACHE_ALIAS

E001 = Error(
    "You must define a '%s' cache in your CACHES setting." % DEFAULT_CACHE_ALIAS,
    id="caches.E001",
)


@register
def check_default_cache_is_configured(package_configs, **kwargs):
    if DEFAULT_CACHE_ALIAS not in settings.CACHES:
        return [E001]
    return []
