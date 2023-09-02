from bolt.packages import PackageConfig


class PackageConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "app"
