# Logs

**Logging configuration and utilities.**

- [Overview](#overview)
- [`app_logger`](#app_logger)
- [Output formats](#output-formats)
- [Context management](#context-management)
- [Debug mode](#debug-mode)
- [Advanced usage](#advanced-usage)
- [Logging settings](#logging-settings)

## Overview

In Python, configuring logging can be surprisingly complex. For most use cases, Plain provides a [default configuration](./configure.py) that "just works".

By default, both the `plain` and `app` loggers are set to the `INFO` level. You can quickly change this by using the `PLAIN_LOG_LEVEL` and `APP_LOG_LEVEL` environment variables.

The `app_logger` supports multiple output formats and provides a friendly kwargs-based API for structured logging.

## `app_logger`

The `app_logger` is an enhanced logger that supports kwargs-style logging and multiple output formats.

```python
from plain.logs import app_logger


def example_function():
    # Basic logging
    app_logger.info("User logged in")

    # With structured context data (explicit **context parameter)
    app_logger.info("User action", user_id=123, action="login", success=True)

    # All log levels support context parameters
    app_logger.debug("Debug info", step="validation", count=5)
    app_logger.warning("Rate limit warning", user_id=456, limit_exceeded=True)
    app_logger.error("Database error", error_code=500, table="users")

    # Standard logging parameters with context
    try:
        risky_operation()
    except Exception:
        app_logger.error(
            "Operation failed",
            exc_info=True,  # Include exception traceback
            stack_info=True,  # Include stack trace
            user_id=789,
            operation="risky_operation"
        )
```

## Output formats

The `app_logger` supports three output formats controlled by the `APP_LOG_FORMAT` environment variable:

### Key-Value format (default)

```bash
export APP_LOG_FORMAT=keyvalue  # or leave unset for default
```

```
[INFO] User action user_id=123 action=login success=True
[ERROR] Database error error_code=500 table=users
```

### JSON format

```bash
export APP_LOG_FORMAT=json
```

```json
{"timestamp": "2024-01-01 12:00:00,123", "level": "INFO", "message": "User action", "user_id": 123, "action": "login", "success": true}
{"timestamp": "2024-01-01 12:00:01,456", "level": "ERROR", "message": "Database error", "error_code": 500, "table": "users"}
```

### Standard format

```bash
export APP_LOG_FORMAT=standard
```

```
[INFO] User action
[ERROR] Database error
```

Note: In standard format, the context kwargs are ignored and not displayed.

## Context management

The `app_logger` provides powerful context management for adding data to multiple log statements.

### Persistent context

Use the `context` dict to add data that persists across log calls:

```python
# Set persistent context
app_logger.context["user_id"] = 123
app_logger.context["request_id"] = "abc456"

app_logger.info("Started processing")      # Includes user_id and request_id
app_logger.info("Validation complete")     # Includes user_id and request_id
app_logger.info("Processing finished")     # Includes user_id and request_id

# Clear context
app_logger.context.clear()
```

### Temporary context

Use `include_context()` for temporary context that only applies within a block:

```python
app_logger.context["user_id"] = 123  # Persistent

with app_logger.include_context(operation="payment", transaction_id="txn789"):
    app_logger.info("Payment started")     # Has user_id, operation, transaction_id
    app_logger.info("Payment validated")   # Has user_id, operation, transaction_id

app_logger.info("Payment complete")        # Only has user_id
```

## Debug mode

The `force_debug()` context manager allows temporarily enabling DEBUG level logging:

```python
# Debug messages might not show at INFO level
app_logger.debug("This might not appear")

# Temporarily enable debug logging
with app_logger.force_debug():
    app_logger.debug("This will definitely appear", extra_data="debug_info")
```

## Advanced usage

### Output streams

By default, Plain splits log output by severity level to ensure proper log classification on cloud platforms:

- **DEBUG, INFO** → `stdout` (standard output)
- **WARNING, ERROR, CRITICAL** → `stderr` (error output)

This behavior ensures that platforms which automatically detect log severity based on output streams correctly classify logs as informational vs errors.

You can customize this behavior using the `PLAIN_LOG_STREAM` environment variable:

```bash
# Default: split by level (INFO to stdout, WARNING+ to stderr)
export PLAIN_LOG_STREAM=split

# Send all logs to stdout (simple, predictable)
export PLAIN_LOG_STREAM=stdout

# Send all logs to stderr (legacy Python behavior)
export PLAIN_LOG_STREAM=stderr
```

## Logging settings

All logging settings can be configured via environment variables:

| Setting               | Environment Variable        | Default      | Description                                              |
| --------------------- | --------------------------- | ------------ | -------------------------------------------------------- |
| `FRAMEWORK_LOG_LEVEL` | `PLAIN_FRAMEWORK_LOG_LEVEL` | `"INFO"`     | Log level for the `plain` logger                         |
| `LOG_LEVEL`           | `PLAIN_LOG_LEVEL`           | `"INFO"`     | Log level for the `app` logger                           |
| `LOG_FORMAT`          | `PLAIN_LOG_FORMAT`          | `"keyvalue"` | Output format: `"json"`, `"keyvalue"`, or `"standard"`   |
| `LOG_STREAM`          | `PLAIN_LOG_STREAM`          | `"split"`    | Output stream mode: `"split"`, `"stdout"`, or `"stderr"` |

**Log levels:** `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`, `"CRITICAL"`
