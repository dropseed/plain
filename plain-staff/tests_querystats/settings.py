from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

SECRET_KEY = "secret"

DEBUG = True

INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.staff.querystats",
]

MIDDLEWARE = [
    "plain.middleware.security.SecurityMiddleware",
    "plain.sessions.middleware.SessionMiddleware",
    "plain.middleware.common.CommonMiddleware",
    "plain.csrf.middleware.CsrfViewMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.middleware.clickjacking.XFrameOptionsMiddleware",
    "plain.staff.querystats.middleware.QueryStatsMiddleware",
]

DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

ROOT_URLCONF = "urls"

USE_TZ = True
