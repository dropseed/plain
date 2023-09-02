from bolt.packages import PackageConfig


class ForgeflagsConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.flags"
    label = "boltflags"  # Primarily for migrations
