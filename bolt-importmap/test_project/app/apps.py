from bolt.apps import AppConfig


class AppConfig(AppConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "app"
