from bolt.packages import PackageConfig


class UsersConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "users"
