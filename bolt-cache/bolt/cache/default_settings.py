# The cache backends to use.
CACHES = {
    "default": {
        "BACKEND": "bolt.cache.backends.locmem.LocMemCache",
    }
}
