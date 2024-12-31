from importlib import import_module
from importlib.util import find_spec

from plain.packages import PackageConfig, packages

MODULE_NAME = "staff"


class Config(PackageConfig):
    name = "plain.staff"
    label = "plainstaff"

    def ready(self):
        def _import_if_exists(module_name):
            if find_spec(module_name):
                import_module(module_name)

        # Trigger register calls to fire by importing the modules
        for package_config in packages.get_package_configs():
            _import_if_exists(f"{package_config.name}.{MODULE_NAME}")

        # Also trigger for the root app/staff.py module
        _import_if_exists(f"app.{MODULE_NAME}")
