from importlib import import_module

from plain.packages import PackageConfig, packages

MODULE_NAME = "staff"


class Config(PackageConfig):
    name = "plain.staff"
    label = "plainstaff"

    def ready(self):
        # Trigger register calls to fire by importing the modules
        for package_config in packages.get_package_configs():
            try:
                import_module(f"{package_config.name}.{MODULE_NAME}")
            except ModuleNotFoundError:
                pass

        # Also trigger for the root app/staff.py module
        try:
            import_module(MODULE_NAME)
        except ModuleNotFoundError:
            pass
