from importlib import import_module

from django.apps import AppConfig, apps

MODULE_NAME = "admin"


class BoltAdminConfig(AppConfig):
    name = "bolt.admin"
    label = "admin"

    def ready(self):
        # Trigger register calls to fire by importing the modules
        for app_config in apps.get_app_configs():
            try:
                import_module(f"{app_config.name}.{MODULE_NAME}")
            except ModuleNotFoundError:
                pass
