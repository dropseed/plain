from bolt.apps import AppConfig


class ForgeflagsConfig(AppConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.flags"
    label = "boltflags"  # Primarily for migrations
