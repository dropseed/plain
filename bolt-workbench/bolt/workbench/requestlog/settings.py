from bolt.runtime import settings


def REQUESTLOG_IGNORE_URL_PATHS():
    return getattr(
        settings,
        "REQUESTLOG_IGNORE_URL_PATHS",
        [
            "/favicon.ico",
            "/favicon.ico/",
            "/admin/jsi18n/",
        ],
    )


def REQUESTLOG_KEEP_LATEST():
    return getattr(settings, "REQUESTLOG_KEEP_LATEST", 50)
