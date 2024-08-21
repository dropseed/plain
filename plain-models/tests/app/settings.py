SECRET_KEY = "test"
INSTALLED_PACKAGES = [
    "plain.models",
    "examples",
]
DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": ":memory:",
    }
}
