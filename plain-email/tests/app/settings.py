SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.email",
]
EMAIL_BACKEND = "plain.email.backends.console.EmailBackend"
EMAIL_DEFAULT_FROM = "test@example.com"
