from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

SECRET_KEY = "secret"

DEBUG = True

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "bolt.sessions",
    # "django.contrib.staticfiles",
    "bolt.stripe",
]

MIDDLEWARE = [
    "bolt.middleware.security.SecurityMiddleware",
    "bolt.sessions.middleware.SessionMiddleware",
    "bolt.middleware.common.CommonMiddleware",
    "bolt.csrf.middleware.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "bolt.middleware.clickjacking.XFrameOptionsMiddleware",
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
            ],
        },
    },
]

STAFFTOOLBAR_LINKS = []
