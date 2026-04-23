from plain.packages import (
    PackageConfig,
    packages_registry,
    register_config,
)

from .otel import register_pool_observables
from .registry import models_registry
from .sources import runtime_pool_source


@register_config
class Config(PackageConfig):
    package_label = "plainpostgres"

    def ready(self) -> None:
        # Trigger register calls to fire by importing the modules
        packages_registry.autodiscover_modules("models", include_app=False)

        models_registry.ready = True

        register_pool_observables(runtime_pool_source)
