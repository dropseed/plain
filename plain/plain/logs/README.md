# Logging

Default logging settings and key-value logger.

In Python, logging can be a surprisingly complex topic.

So Plain aims for easy-to-use defaults that "just work".

## `app_logger`

The default `app_logger` doesn't do much!

But it is paired with the default [settings](#) to actually show the logs like you would expect,
without any additional configuration.

```python
from plain.logs import app_logger


def example_function():
    app_logger.info("Hey!")
```

## `app_logger.kv`
