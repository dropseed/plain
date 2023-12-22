from bolt.packages import PackageConfig


class BoltCacheConfig(PackageConfig):
    default_auto_field = "bolt.db.models.BigAutoField"
    name = "bolt.cache"
    label = "boltcache"
