from importlib import import_module

from bolt.packages import PackageConfig, packages

MODULE_NAME = "jobs"


class BoltJobsConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.worker"
    label = "boltqueue"

    def ready(self):
        # Trigger register calls to fire by importing the modules
        for package_config in packages.get_package_configs():
            try:
                import_module(f"{package_config.name}.{MODULE_NAME}")
            except ModuleNotFoundError:
                pass

        # Also trigger for the root app/admin.py module
        try:
            import_module(MODULE_NAME)
        except ModuleNotFoundError:
            pass
