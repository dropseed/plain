# Logs

**Logging configuration and utilities.**

In Python, configuring logging can be surprisingly complex. For most use cases, Plain provides a [default configuration](./configure.py) that "just works".

By default, both the `plain` and `app` loggers are set to the `INFO` level. You can quickly change this by using the `PLAIN_LOG_LEVEL` and `APP_LOG_LEVEL` environment variables.

## `app_logger`

The `app_logger` is a pre-configured logger you can use inside your app code.

```python
from plain.logs import app_logger


def example_function():
    app_logger.info("Hey!")
```

## `app_logger.kv`

The key-value logging format is popular for outputting more structured logs that are still human-readable.

```python
from plain.logs import app_logger


def example_function():
    app_logger.kv("Example log line with", example_key="example_value")
```

## Logging settings

You can further configure your logging with `settings.LOGGING`.

```python
# app/settings.py
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "mylogger": {
            "handlers": ["console"],
            "level": "DEBUG",
        },
    },
}
```
