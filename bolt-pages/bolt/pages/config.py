import os

from bolt.packages import PackageConfig, packages
from bolt.runtime import settings

from .registry import registry


class BoltPagesConfig(PackageConfig):
    name = "bolt.pages"

    def ready(self):
        for pacakge_config in packages.get_package_configs():
            registry.discover_pages(os.path.join(pacakge_config.path, "pages"))

        registry.discover_pages(os.path.join(settings.APP_PATH, "pages"))
