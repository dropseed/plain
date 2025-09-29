import logging

from .formatters import JSONFormatter, KeyValueFormatter


def configure_logging(
    *, plain_log_level: int | str, app_log_level: int | str, app_log_format: str
) -> None:
    # Create and configure the plain logger (uses standard Logger, not AppLogger)
    plain_logger = logging.Logger("plain")
    plain_logger.setLevel(plain_log_level)
    plain_handler = logging.StreamHandler()
    plain_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    plain_logger.addHandler(plain_handler)
    plain_logger.propagate = False
    logging.root.manager.loggerDict["plain"] = plain_logger

    # Configure the existing app_logger
    from .loggers import app_logger

    app_logger.setLevel(app_log_level)
    app_logger.propagate = False

    app_handler = logging.StreamHandler()
    match app_log_format:
        case "json":
            app_handler.setFormatter(JSONFormatter("%(json)s"))
        case "keyvalue":
            app_handler.setFormatter(
                KeyValueFormatter("[%(levelname)s] %(message)s %(keyvalue)s")
            )
        case _:
            app_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    app_logger.addHandler(app_handler)

    # Register the app_logger in the logging system so getLogger("app") returns it
    logging.root.manager.loggerDict["app"] = app_logger
