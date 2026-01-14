# Logs

**Structured logging with sensible defaults and zero configuration.**

- [Overview](#overview)
- [Using app_logger](#using-app_logger)
    - [Basic logging](#basic-logging)
    - [Adding context](#adding-context)
- [Output formats](#output-formats)
    - [Key-value format](#key-value-format)
    - [JSON format](#json-format)
    - [Standard format](#standard-format)
- [Context management](#context-management)
    - [Persistent context](#persistent-context)
    - [Temporary context](#temporary-context)
- [Debug mode](#debug-mode)
- [Output streams](#output-streams)
- [Settings reference](#settings-reference)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Python's logging module is powerful but notoriously difficult to configure. Plain provides a ready-to-use logging setup that works out of the box while supporting structured logging for production environments.

You get two pre-configured loggers: `plain` (for framework internals) and `app` (for your application code). Both default to the `INFO` level and can be adjusted via environment variables.

```python
from plain.logs import app_logger

# Simple message logging
app_logger.info("Application started")

# Structured logging with context data
app_logger.info("User logged in", context={"user_id": 123, "method": "oauth"})

# All log levels work the same way
app_logger.warning("Rate limit approaching", context={"requests": 95, "limit": 100})
app_logger.error("Payment failed", context={"order_id": "abc-123", "reason": "insufficient_funds"})
```

## Using app_logger

### Basic logging

The [`app_logger`](./app.py#AppLogger) supports all standard logging levels: `debug`, `info`, `warning`, `error`, and `critical`.

```python
app_logger.debug("Entering validation step")
app_logger.info("Request processed successfully")
app_logger.warning("Cache miss, falling back to database")
app_logger.error("Failed to connect to external service")
app_logger.critical("Database connection pool exhausted")
```

### Adding context

Pass structured data using the `context` parameter. This data appears in your log output based on your chosen format.

```python
app_logger.info("Order placed", context={
    "order_id": "ord-456",
    "items": 3,
    "total": 99.99,
})
```

You can also include exception tracebacks:

```python
try:
    process_payment()
except PaymentError:
    app_logger.error(
        "Payment processing failed",
        exc_info=True,
        context={"order_id": "ord-456"},
    )
```

## Output formats

Control the log format with the `APP_LOG_FORMAT` environment variable.

### Key-value format

The default format. Context data appears as `key=value` pairs, easy for humans to read and machines to parse.

```bash
export APP_LOG_FORMAT=keyvalue
```

```
[INFO] User logged in user_id=123 method=oauth
[ERROR] Payment failed order_id="abc-123" reason="insufficient_funds"
```

### JSON format

Each log entry is a single JSON object. Ideal for log aggregation services like Datadog, Splunk, or CloudWatch.

```bash
export APP_LOG_FORMAT=json
```

```json
{"timestamp": "2024-01-15 10:30:00,123", "level": "INFO", "message": "User logged in", "logger": "app", "user_id": 123, "method": "oauth"}
```

### Standard format

A minimal format that omits context data entirely.

```bash
export APP_LOG_FORMAT=standard
```

```
[INFO] User logged in
```

## Context management

### Persistent context

Add context that applies to all subsequent log calls by modifying the `context` dict directly.

```python
# Set context at the start of a request
app_logger.context["request_id"] = "req-789"
app_logger.context["user_id"] = 42

app_logger.info("Starting request")  # Includes request_id and user_id
app_logger.info("Fetching data")     # Includes request_id and user_id

# Clear when done
app_logger.context.clear()
```

### Temporary context

Use `include_context()` when you need context for a specific block of code.

```python
app_logger.context["user_id"] = 42

with app_logger.include_context(operation="checkout", cart_id="cart-123"):
    app_logger.info("Starting checkout")  # Has user_id, operation, cart_id
    app_logger.info("Validating items")   # Has user_id, operation, cart_id

app_logger.info("Checkout complete")      # Only has user_id
```

## Debug mode

When you need to temporarily see debug-level logs (even if the logger is set to `INFO`), use `force_debug()`.

```python
# These won't show if log level is INFO
app_logger.debug("Detailed trace info")

# Temporarily enable debug output
with app_logger.force_debug():
    app_logger.debug("This will appear")
    app_logger.debug("So will this", context={"step": "validation"})

# Back to normal
app_logger.debug("This won't show again")
```

The [`DebugMode`](./debug.py#DebugMode) class handles reference counting, so nested `force_debug()` calls work correctly.

## Output streams

By default, Plain splits log output by severity:

- **DEBUG, INFO** go to `stdout`
- **WARNING, ERROR, CRITICAL** go to `stderr`

This helps cloud platforms automatically classify log severity. You can change this behavior with `PLAIN_LOG_STREAM`:

```bash
# Default: split by level
export PLAIN_LOG_STREAM=split

# All logs to stdout
export PLAIN_LOG_STREAM=stdout

# All logs to stderr (traditional Python behavior)
export PLAIN_LOG_STREAM=stderr
```

## Settings reference

All logging settings use environment variables:

| Environment Variable        | Default    | Description                                      |
| --------------------------- | ---------- | ------------------------------------------------ |
| `PLAIN_FRAMEWORK_LOG_LEVEL` | `INFO`     | Log level for the `plain` logger                 |
| `PLAIN_LOG_LEVEL`           | `INFO`     | Log level for the `app` logger                   |
| `PLAIN_LOG_FORMAT`          | `keyvalue` | Output format: `json`, `keyvalue`, or `standard` |
| `PLAIN_LOG_STREAM`          | `split`    | Output stream: `split`, `stdout`, or `stderr`    |

Valid log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

## FAQs

#### How do I use a custom logger instead of app_logger?

You can use Python's standard `logging.getLogger()` for additional loggers. They won't have the context features of `app_logger`, but they'll use Plain's output configuration.

#### Can I use app_logger in library code?

The `app_logger` is designed for application code. If you're writing a reusable library, use `logging.getLogger(__name__)` to allow users to configure logging independently.

#### Why are my debug logs not showing?

The default log level is `INFO`. Set `PLAIN_LOG_LEVEL=DEBUG` in your environment or use `app_logger.force_debug()` temporarily.

#### How do I add context to exception logs?

Pass both `exc_info=True` and `context` to include both the traceback and structured data:

```python
except Exception:
    app_logger.error("Operation failed", exc_info=True, context={"operation": "sync"})
```

## Installation

`plain.logs` is included with Plain by default. No additional installation is required.

To adjust log levels for development, add environment variables to your shell or `.env` file:

```bash
PLAIN_LOG_LEVEL=DEBUG
PLAIN_FRAMEWORK_LOG_LEVEL=WARNING
```
