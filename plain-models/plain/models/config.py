from plain.packages import PackageConfig


class PlainDBConfig(PackageConfig):
    name = "plain.models"
    # We wan to use the "migrations" module
    # in this package but not for the standard purpose
    migrations_module = None
