from plain.packages import (
    PackageConfig,
    packages_registry,
    register_config,
)

from .registry import models_registry


@register_config
class Config(PackageConfig):
    def ready(self):
        # Trigger register calls to fire by importing the modules
        packages_registry.autodiscover_modules("models", include_app=False)

        models_registry.ready = True
