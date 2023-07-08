from django.apps import AppConfig


class ForgeflagsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bolt.flags"
    label = "boltflags"  # Primarily for migrations
