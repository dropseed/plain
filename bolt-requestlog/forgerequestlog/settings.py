from django.conf import settings


def REQUESTLOG_IGNORE_URL_PATHS():
    return getattr(
        settings,
        "REQUESTLOG_IGNORE_URL_PATHS",
        [
            "/sw.js",
            "/favicon.ico",
            "/admin/jsi18n/",
        ],
    )


def REQUESTLOG_KEEP_LATEST():
    return getattr(settings, "REQUESTLOG_KEEP_LATEST", 50)


def REQUESTLOG_URL():
    return getattr(settings, "REQUESTLOG_URL", "/requestlog/")
