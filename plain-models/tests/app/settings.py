SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.models",
    "app.examples",
]
DATABASE = {
    "ENGINE": "plain.models.backends.sqlite3",
    "NAME": ":memory:",
}
