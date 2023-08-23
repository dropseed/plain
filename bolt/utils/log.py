from os import environ
import logging
import logging.config

from bolt.legacy.management.color import color_style
from bolt.runtime import settings

request_logger = logging.getLogger("bolt.request")

# Default logging for Bolt. This sends an email to the site admins on every
# HTTP 500 error. Depending on DEBUG, all other log records are either sent to
# the console (DEBUG=True) or discarded (DEBUG=False) by means of the
# require_debug_true filter. This configuration is quoted in
# docs/ref/logging.txt; please amend it there if edited here.
DEFAULT_LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "require_debug_false": {
            "()": "bolt.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "bolt.utils.log.RequireDebugTrue",
        },
    },
    "formatters": {
        "simple": {
            "format": "[%(levelname)s] %(message)s",
        },
        "bolt.server": {
            "()": "bolt.utils.log.ServerFormatter",
            "format": "[{server_time}] {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "filters": ["require_debug_true"],
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "bolt.server": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "bolt.server",
        },
    },
    "loggers": {
        "bolt": {
            "handlers": ["console"],
            "level": environ.get("BOLT_LOG_LEVEL", "INFO"),
        },
        "bolt.server": {
            "handlers": ["bolt.server"],
            "level": "INFO",
            "propagate": False,
        },
        "app": {
            "handlers": ["console"],
            "level": environ.get("APP_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}


def configure_logging(logging_settings):
    # Load the defaults
    logging.config.dictConfig(DEFAULT_LOGGING)

    # Then customize it from settings
    if logging_settings:
        logging.config.dictConfig(logging_settings)


class CallbackFilter(logging.Filter):
    """
    A logging filter that checks the return value of a given callable (which
    takes the record-to-be-logged as its only parameter) to decide whether to
    log a record.
    """

    def __init__(self, callback):
        self.callback = callback

    def filter(self, record):
        if self.callback(record):
            return 1
        return 0


class RequireDebugFalse(logging.Filter):
    def filter(self, record):
        return not settings.DEBUG


class RequireDebugTrue(logging.Filter):
    def filter(self, record):
        return settings.DEBUG


class ServerFormatter(logging.Formatter):
    default_time_format = "%d/%b/%Y %H:%M:%S"

    def __init__(self, *args, **kwargs):
        self.style = color_style()
        super().__init__(*args, **kwargs)

    def format(self, record):
        msg = record.msg
        status_code = getattr(record, "status_code", None)

        if status_code:
            if 200 <= status_code < 300:
                # Put 2XX first, since it should be the common case
                msg = self.style.HTTP_SUCCESS(msg)
            elif 100 <= status_code < 200:
                msg = self.style.HTTP_INFO(msg)
            elif status_code == 304:
                msg = self.style.HTTP_NOT_MODIFIED(msg)
            elif 300 <= status_code < 400:
                msg = self.style.HTTP_REDIRECT(msg)
            elif status_code == 404:
                msg = self.style.HTTP_NOT_FOUND(msg)
            elif 400 <= status_code < 500:
                msg = self.style.HTTP_BAD_REQUEST(msg)
            else:
                # Any 5XX, or any other status code
                msg = self.style.HTTP_SERVER_ERROR(msg)

        if self.uses_server_time() and not hasattr(record, "server_time"):
            record.server_time = self.formatTime(record, self.datefmt)

        record.msg = msg
        return super().format(record)

    def uses_server_time(self):
        return self._fmt.find("{server_time}") >= 0


def log_response(
    message,
    *args,
    response=None,
    request=None,
    logger=request_logger,
    level=None,
    exception=None,
):
    """
    Log errors based on HttpResponse status.

    Log 5xx responses as errors and 4xx responses as warnings (unless a level
    is given as a keyword argument). The HttpResponse status_code and the
    request are passed to the logger's extra parameter.
    """
    # Check if the response has already been logged. Multiple requests to log
    # the same response can be received in some cases, e.g., when the
    # response is the result of an exception and is logged when the exception
    # is caught, to record the exception.
    if getattr(response, "_has_been_logged", False):
        return

    if level is None:
        if response.status_code >= 500:
            level = "error"
        elif response.status_code >= 400:
            level = "warning"
        else:
            level = "info"

    getattr(logger, level)(
        message,
        *args,
        extra={
            "status_code": response.status_code,
            "request": request,
        },
        exc_info=exception,
    )
    response._has_been_logged = True
