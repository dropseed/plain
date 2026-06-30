SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.postgres",
    "plain.redirection",
]
MIDDLEWARE = [
    "plain.redirection.RedirectionMiddleware",
]
