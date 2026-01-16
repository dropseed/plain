# Server

**A production-ready WSGI HTTP server based on gunicorn.**

- [Overview](#overview)
- [Worker types](#worker-types)
- [Configuration options](#configuration-options)
- [Environment variables](#environment-variables)
- [Signals](#signals)
- [Using a different WSGI server](#using-a-different-wsgi-server)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can run the built-in HTTP server with the `plain server` command.

```bash
plain server
```

By default, the server binds to `127.0.0.1:8000` and uses a single worker process. In production, you will typically want to increase the number of workers and optionally enable threading.

```bash
# Run with 4 worker processes
plain server --workers 4

# Auto-detect based on available CPUs
plain server --workers auto

# Run with 2 workers and 4 threads each
plain server --workers 2 --threads 4
```

For local development, you can enable auto-reload to restart workers when code changes.

```bash
plain server --reload
```

## Worker types

The server automatically selects the worker type based on your configuration.

**Sync workers** handle one request at a time per worker. These are simple and predictable.

```bash
# Single-threaded (uses sync worker)
plain server --workers 4
```

**Threaded workers** handle multiple concurrent requests per worker using a thread pool. These are useful when your application does blocking I/O.

```bash
# Multi-threaded (uses threaded worker)
plain server --workers 2 --threads 8
```

For advanced worker customization, see the [`SyncWorker`](./workers/sync.py#SyncWorker) and [`ThreadWorker`](./workers/thread.py#ThreadWorker) classes.

## Configuration options

All options are available via the command line. Run `plain server --help` to see the full list.

| Option             | Default          | Description                                           |
| ------------------ | ---------------- | ----------------------------------------------------- |
| `--bind` / `-b`    | `127.0.0.1:8000` | Address to bind (can be used multiple times)          |
| `--workers` / `-w` | `1`              | Number of worker processes (or `auto` for CPU count)  |
| `--threads`        | `1`              | Number of threads per worker                          |
| `--timeout` / `-t` | `30`             | Worker timeout in seconds                             |
| `--reload`         | `False`          | Restart workers when code changes                     |
| `--certfile`       | -                | Path to SSL certificate file                          |
| `--keyfile`        | -                | Path to SSL key file                                  |
| `--log-level`      | `info`           | Logging level (debug, info, warning, error, critical) |
| `--access-log`     | `-` (stdout)     | Access log file path                                  |
| `--error-log`      | `-` (stderr)     | Error log file path                                   |
| `--max-requests`   | `0` (disabled)   | Max requests before worker restart                    |
| `--pidfile`        | -                | PID file path                                         |

## Environment variables

| Variable              | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `WEB_CONCURRENCY`     | Sets the number of workers (use `auto` to detect CPU cores, or a number) |
| `SENDFILE`            | Enable sendfile() syscall (`1`, `yes`, `true`, or `y` to enable)         |
| `FORWARDED_ALLOW_IPS` | Comma-separated list of trusted proxy IPs (default: `127.0.0.1,::1`)     |

## Signals

The server responds to UNIX signals for process management.

| Signal    | Effect                           |
| --------- | -------------------------------- |
| `SIGTERM` | Graceful shutdown                |
| `SIGINT`  | Quick shutdown                   |
| `SIGQUIT` | Quick shutdown                   |
| `SIGHUP`  | Reload configuration and workers |
| `SIGTTIN` | Increase worker count by 1       |
| `SIGTTOU` | Decrease worker count by 1       |
| `SIGUSR1` | Reopen log files                 |

## Using a different WSGI server

You can use any WSGI-compatible server instead of the built-in one. Plain provides a standard WSGI application interface at `plain.wsgi:app`.

```bash
# Using uvicorn
uvicorn plain.wsgi:app --port 8000

# Using waitress
waitress-serve --port=8000 plain.wsgi:app

# Using gunicorn directly
gunicorn plain.wsgi:app --workers 4
```

## FAQs

#### How do I run with SSL/TLS?

Provide both `--certfile` and `--keyfile` options pointing to your certificate and key files.

```bash
plain server --certfile cert.pem --keyfile key.pem
```

#### How do I run behind a reverse proxy?

Configure your proxy to pass the appropriate headers, then set `FORWARDED_ALLOW_IPS` to include your proxy's IP address.

```bash
FORWARDED_ALLOW_IPS="10.0.0.1,10.0.0.2" plain server --bind 0.0.0.0:8000
```

The server recognizes `X-Forwarded-Proto`, `X-Forwarded-Protocol`, and `X-Forwarded-SSL` headers from trusted proxies.

#### How do I handle worker timeouts?

If workers are being killed due to timeouts, increase the `--timeout` value. This is common when handling long-running requests.

```bash
plain server --timeout 120
```

#### How do I rotate log files?

Send `SIGUSR1` to the master process to reopen log files. This works with tools like `logrotate`.

```bash
kill -USR1 $(cat /path/to/pidfile)
```

## Installation

The server module is included with Plain. No additional installation is required.
