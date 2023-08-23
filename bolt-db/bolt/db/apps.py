from bolt.apps import AppConfig


class BoltDBConfig(AppConfig):
    name = "bolt.db"
    # We wan to use the "migrations" module
    # in this package but not for the standard purpose
    migrations_module = None
