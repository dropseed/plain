SECRET_KEY = "test"
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.models",
    "plain.htmx",
    "plain.tailwind",
    "plain.staff",
    "app.users",
]
DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": ":memory:",
    }
}
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.staff.StaffMiddleware",
]
AUTH_LOGIN_URL = "login"
AUTH_USER_MODEL = "users.User"
