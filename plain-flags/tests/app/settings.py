SECRET_KEY = "test"
INSTALLED_PACKAGES = [
    "plain.models",
    "plain.flags",
]
DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": ":memory:",
    }
}
