import os

from plain.packages import PackageConfig, packages
from plain.runtime import APP_PATH

from .registry import registry


class PlainPagesConfig(PackageConfig):
    name = "plain.pages"

    def ready(self):
        for pacakge_config in packages.get_package_configs():
            registry.discover_pages(
                os.path.join(pacakge_config.path, "templates", "pages")
            )

        registry.discover_pages(os.path.join(APP_PATH, "templates", "pages"))
