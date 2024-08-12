from os import environ
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "test"

DEBUG = True

INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "users",
    "plain.oauth",
]

MIDDLEWARE = [
    "plain.middleware.security.SecurityMiddleware",
    "plain.sessions.middleware.SessionMiddleware",
    "plain.middleware.common.CommonMiddleware",
    "plain.csrf.middleware.CsrfViewMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "urls"

DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

USE_TZ = True
TIME_ZONE = "UTC"

AUTH_LOGIN_URL = "login"
LOGOUT_REDIRECT_URL = "/"

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
