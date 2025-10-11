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

- `bind` - Address to bind to (default: `127.0.0.1:8000`)
- `workers` - Number of worker processes (default: 1)
- `threads` - Number of threads per worker (default: 1)
- `timeout` - Worker timeout in seconds (default: 30)
- `keepalive` - Seconds to wait for requests on a Keep-Alive connection (default: 2)
- `reload` - Enable auto-reload on code changes (default: False)
- `reload_extra_files` - Additional files to watch for reloading
- `certfile` - Path to SSL certificate file
- `keyfile` - Path to SSL key file
- `loglevel` - Logging level: debug, info, warning, error, critical (default: info)
- `accesslog` - Access log file path (use `-` for stdout)
- `errorlog` - Error log file path (use `-` for stderr)

For a complete list of options, see the gunicorn documentation or the configuration in `plain.server.config`.

## WSGI Ejection Point

While Plain includes this built-in server, you can still use any WSGI-compatible server you prefer. Plain's `wsgi.py` module provides a standard WSGI application interface:

```bash
# Using uvicorn
uvicorn plain.wsgi:app --port 8000

# Using waitress
waitress-serve --port=8000 plain.wsgi:app

# Using external gunicorn
gunicorn plain.wsgi:app --workers 4
```
