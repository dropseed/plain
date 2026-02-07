import os

from plain.packages import PackageConfig, packages_registry, register_config
from plain.runtime import APP_PATH

from .registry import pages_registry


@register_config
class Config(PackageConfig):
    package_label = "plainpages"

    def ready(self) -> None:
        for pacakge_config in packages_registry.get_package_configs():
            pages_registry.discover_pages(
                os.path.join(pacakge_config.path, "templates", "pages")
            )

        pages_registry.discover_pages(os.path.join(APP_PATH, "templates", "pages"))
