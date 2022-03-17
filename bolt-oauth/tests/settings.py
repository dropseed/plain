from os import environ
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "test"

DEBUG = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "users",
    "oauth_login",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

USE_TZ = True
TIME_ZONE = "UTC"

STATIC_URL = "/static/"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

AUTH_USER_MODEL = "users.User"

OAUTH_LOGIN_PROVIDERS = {
    "github": {
        "class": "providers.github.GitHubOAuthProvider",
        "kwargs": {
            "client_id": environ["GITHUB_CLIENT_ID"],
            "client_secret": environ["GITHUB_CLIENT_SECRET"],
        },
    },
    "bitbucket": {
        "class": "providers.bitbucket.BitbucketOAuthProvider",
        "kwargs": {
            "client_id": environ["BITBUCKET_KEY"],
            "client_secret": environ["BITBUCKET_SECRET"],
        },
    },
    "gitlab": {
        "class": "providers.gitlab.GitLabOAuthProvider",
        "kwargs": {
            "client_id": environ["GITLAB_APPLICATION_ID"],
            "client_secret": environ["GITLAB_APPLICATION_SECRET"],
            "scope": "read_user",
        },
    },
}
