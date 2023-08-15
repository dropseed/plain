from bolt.apps import AppConfig


class BoltOAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bolt.oauth"
    label = "boltoauth"  # Primarily for migrations
