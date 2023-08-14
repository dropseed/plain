from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

SECRET_KEY = "secret"

DEBUG = True

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "bolt.sessions",
    "django.contrib.messages",
    # "django.contrib.staticfiles",
    "boltquerystats",
]

MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",
    "boltquerystats.middleware.QueryStatsMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

ROOT_URLCONF = "urls"

USE_TZ = True

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

STAFFTOOLBAR_LINKS = []
