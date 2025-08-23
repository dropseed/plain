from importlib import import_module
from importlib.util import find_spec

from plain.packages import PackageConfig, packages_registry, register_config


@register_config
class Config(PackageConfig):
    def ready(self):
        def _import_if_exists(module_name):
            if find_spec(module_name):
                import_module(module_name)

        # Trigger register calls to fire by importing the toolbar modules
        for package_config in packages_registry.get_package_configs():
            _import_if_exists(f"{package_config.name}.toolbar")

        # Also trigger for the root app/toolbar.py module
        _import_if_exists("app.toolbar")
