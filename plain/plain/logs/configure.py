import logging
import logging.config
from os import environ


def configure_logging(logging_settings):
    # Load the defaults
    default_logging = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "simple": {
                "format": "[%(levelname)s] %(message)s",
            },
        },
        "handlers": {
            "plain_console": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "formatter": "simple",
            },
            "app_console": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "formatter": "simple",
            },
        },
        "loggers": {
            "plain": {
                "handlers": ["plain_console"],
                "level": environ.get("PLAIN_LOG_LEVEL", "INFO"),
            },
            "app": {
                "handlers": ["app_console"],
                "level": environ.get("APP_LOG_LEVEL", "INFO"),
                "propagate": False,
            },
        },
    }
    logging.config.dictConfig(default_logging)

    # Then customize it from settings
    if logging_settings:
        logging.config.dictConfig(logging_settings)
