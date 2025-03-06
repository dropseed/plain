from os import environ

SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.models",
    "plain.oauth",
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
]
AUTH_LOGIN_URL = "login"
AUTH_USER_MODEL = "users.User"

# OAuth providers to use for a real, interactive test
# (in a real config you'd probably do environ["key"] to raise a KeyError if an env var is forgotten)
OAUTH_LOGIN_PROVIDERS = {
    "github": {
        "class": "providers.github.GitHubOAuthProvider",
        "kwargs": {
            "client_id": environ.get("GITHUB_CLIENT_ID"),
            "client_secret": environ.get("GITHUB_CLIENT_SECRET"),
        },
    },
    "bitbucket": {
        "class": "providers.bitbucket.BitbucketOAuthProvider",
        "kwargs": {
            "client_id": environ.get("BITBUCKET_KEY"),
            "client_secret": environ.get("BITBUCKET_SECRET"),
        },
    },
    "gitlab": {
        "class": "providers.gitlab.GitLabOAuthProvider",
        "kwargs": {
            "client_id": environ.get("GITLAB_APPLICATION_ID"),
            "client_secret": environ.get("GITLAB_APPLICATION_SECRET"),
            "scope": "read_user",
        },
    },
}
