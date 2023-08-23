from bolt.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "users"
