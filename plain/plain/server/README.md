# plain.server

**Plain's internal HTTP server based on vendored gunicorn.**

## Overview

This module provides a WSGI HTTP server for Plain applications. It is based on [gunicorn](https://gunicorn.org), which has been vendored into Plain's core to provide better integration and control over the HTTP server layer.

The server is designed to work seamlessly with Plain's development workflow while still maintaining WSGI compatibility, allowing you to eject to any alternative WSGI server if needed.

## Usage

### Command Line

The simplest way to run the server is using the `plain server` command:

```bash
# Run with defaults (127.0.0.1:8000)
plain server

# Specify host and port
plain server --bind 0.0.0.0:8080

# Run with SSL
plain server --certfile cert.pem --keyfile key.pem

# Enable auto-reload for development
plain server --reload

# Use multiple threads
plain server --threads 8
```

## Configuration Options

Common options:

- `--bind` / `-b` - Address to bind to (default: `127.0.0.1:8000`)
- `--workers` / `-w` - Number of worker processes (default: 1, or `$WEB_CONCURRENCY` env var)
- `--threads` - Number of threads per worker (default: 1)
- `--timeout` / `-t` - Worker timeout in seconds (default: 30)
- `--reload` - Enable auto-reload on code changes, including `.env*` files (default: False)
- `--certfile` - Path to SSL certificate file
- `--keyfile` - Path to SSL key file
- `--log-level` - Logging level: debug, info, warning, error, critical (default: info)
- `--access-log` - Access log file path (default: `-` for stdout)
- `--error-log` - Error log file path (default: `-` for stderr)
- `--log-format` - Log format string for error logs
- `--access-log-format` - Access log format string for HTTP request details
- `--max-requests` - Max requests before worker restart (default: 0, disabled)
- `--pidfile` - PID file path

### Environment Variables

- `WEB_CONCURRENCY` - Sets the number of worker processes (commonly used by Heroku and other PaaS providers)
- `SENDFILE` - Enable/disable use of sendfile() syscall (set to `1`, `yes`, `true`, or `y` to enable)
- `FORWARDED_ALLOW_IPS` - Comma-separated list of trusted proxy IPs for secure headers (default: `127.0.0.1,::1`)

For a complete list of options, run `plain server --help`.

## WSGI Ejection Point

While Plain includes this built-in server, you can still use any WSGI-compatible server you prefer. Plain's `wsgi.py` module provides a standard WSGI application interface:

```bash
# Using uvicorn
uvicorn plain.wsgi:app --port 8000

# Using waitress
waitress-serve --port=8000 plain.wsgi:app

# Using gunicorn as an alternative
gunicorn plain.wsgi:app --workers 4
```
