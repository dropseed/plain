from bolt.packages import PackageConfig


class BoltOAuthConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.oauth"
    label = "boltoauth"  # Primarily for migrations
