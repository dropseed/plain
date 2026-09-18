"""
Default Plain settings. Override these with settings in the module pointed to
by the PLAIN_SETTINGS_MODULE environment variable.
"""

import os

from .secret import Secret
from .utils import get_app_info_from_pyproject

# MARK: Core Settings

DEBUG: bool = False

name, version = get_app_info_from_pyproject()
NAME: str = name
VERSION: str = version

# List of strings representing installed packages.
INSTALLED_PACKAGES: list[str] = []

URLS_ROUTER: str

# Whether routes have trailing slashes by default. Routes can override
# per-endpoint with `path(..., force_slash=True|False)`. Requests that
# disagree with a route's effective form are 308-redirected to it.
URLS_TRAILING_SLASH: bool = False

# List of environment variable prefixes to check for settings.
# Settings can be configured via environment variables using these prefixes.
# Example: ENV_SETTINGS_PREFIXES = ["PLAIN_", "MYAPP_"]
# Then both PLAIN_DEBUG and MYAPP_DEBUG would set the DEBUG setting.
ENV_SETTINGS_PREFIXES: list[str] = ["PLAIN_"]

# MARK: HTTP and Security

# Hosts/domain names that are valid for this site.
# - An empty list [] allows all hosts (useful for development).
# - ".example.com" matches example.com and all subdomains
# - "192.168.1.0/24" matches IP addresses in that CIDR range
ALLOWED_HOSTS: list[str] = []

# Path for the built-in healthcheck endpoint.
# When set, the server responds directly on the event loop with a 200 "ok"
# before the thread pool or any middleware runs.
# Example: HEALTHCHECK_PATH = "/up/"
HEALTHCHECK_PATH: str = ""

# Default headers for all responses.
# Header values can include {request.attribute} placeholders for dynamic content.
# Example: "script-src 'nonce-{request.csp_nonce}'" will use the request's nonce.
# Views can override, remove, or extend these headers - see plain/http/README.md
# for customization patterns.
DEFAULT_RESPONSE_HEADERS: dict = {
    # "Content-Security-Policy": "default-src 'self'; script-src 'self' 'nonce-{request.csp_nonce}'",
    # https://hstspreload.org/
    # "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

# Whether to redirect all non-HTTPS requests to HTTPS (blanket redirect).
# For anything more advanced (custom host, path exemptions, etc.), write
# your own middleware.
HTTPS_REDIRECT_ENABLED: bool = True

# If your Plain app is behind a proxy that sets a header to specify secure
# connections, AND that proxy ensures that user-submitted headers with the
# same name are ignored (so that people can't spoof it), set this value to
# a string in the format "Header-Name: value". For any requests that come in
# with that header/value, request.is_https() will return True.
# WARNING! Only set this if you fully understand what you're doing. Otherwise,
# you may be opening yourself up to a security risk.
# Example: HTTPS_PROXY_HEADER = "X-Forwarded-Proto: https"
HTTPS_PROXY_HEADER: str = ""

# Whether to use the X-Forwarded-Host, X-Forwarded-Port, and X-Forwarded-For
# headers when determining the host, port, and client IP for the request.
# Only enable these when behind a trusted proxy that overwrites these headers.
HTTP_X_FORWARDED_HOST: bool = False
HTTP_X_FORWARDED_PORT: bool = False
HTTP_X_FORWARDED_FOR: bool = False

# A secret key for this particular Plain installation. Used in secret-key
# hashing algorithms. Set this in your settings, or Plain will complain
# loudly.
SECRET_KEY: Secret[str]

# List of secret keys used to verify the validity of signatures. This allows
# secret key rotation.
SECRET_KEY_FALLBACKS: Secret[list[str]] = []

# MARK: Internationalization

# Local time zone for this installation. All choices can be found here:
# https://en.wikipedia.org/wiki/List_of_tz_zones_by_name (although not all
# systems may support all possibilities). This is interpreted as the default
# user time zone.
TIME_ZONE: str = "UTC"


# MARK: URL Configuration

# The base URL of the site, used to generate absolute URLs outside of request contexts.
# Should include scheme and host with no trailing slash (e.g. "https://example.com").
BASE_URL: str = ""

# MARK: File Uploads

# List of upload handler classes to be applied in order.
FILE_UPLOAD_HANDLERS: list[str] = [
    "plain.internal.files.uploadhandler.MemoryFileUploadHandler",
    "plain.internal.files.uploadhandler.TemporaryFileUploadHandler",
]

# Maximum size, in bytes, of a request before it will be streamed to the
# file system instead of into memory.
FILE_UPLOAD_MAX_MEMORY_SIZE: int = 2621440  # i.e. 2.5 MB

# Maximum size in bytes of request data (excluding file uploads) that will be
# read into memory before a ContentTooLargeError413 is raised. This bounds
# what request.body/form parsing materializes in RAM — the server-edge cap
# on total request body size is SERVER_MAX_REQUEST_BODY_SIZE.
DATA_UPLOAD_MAX_MEMORY_SIZE: int = 2621440  # i.e. 2.5 MB

# Maximum number of GET/POST parameters that will be read before a
# SuspiciousOperationError400 (TooManyFieldsSentError400) is raised.
DATA_UPLOAD_MAX_NUMBER_FIELDS: int = 1000

# Maximum number of files encoded in a multipart upload that will be read
# before a SuspiciousOperationError400 (TooManyFilesSentError400) is raised.
DATA_UPLOAD_MAX_NUMBER_FILES: int = 100

# Directory in which upload streamed files will be temporarily saved. A value of
# `None` will make Plain use the operating system's default temporary directory
# (i.e. "/tmp" on *nix systems).
FILE_UPLOAD_TEMP_DIR: str | None = None

# MARK: Middleware

# List of middleware to use. Order is important; in the request phase, these
# middleware will be applied in the order given, and in the response
# phase the middleware will be applied in reverse order.
MIDDLEWARE: list[str] = []

# MARK: CSRF

# A list of trusted origins for unsafe (POST/PUT/DELETE etc.) requests.
# These origins will be allowed regardless of the normal CSRF checks.
# Each origin should be a full origin like "https://example.com" or "https://sub.example.com:8080"
CSRF_TRUSTED_ORIGINS: list[str] = []

# Regex patterns for paths that should be exempt from CSRF protection
# Examples: [r"^/api/", r"/webhooks/.*", r"/health$"]
CSRF_EXEMPT_PATHS: list[str] = []

# MARK: Logging

FRAMEWORK_LOG_LEVEL: str = "INFO"
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "keyvalue"
LOG_STREAM: str = "split"  # "split", "stdout", or "stderr"

# MARK: Server

SERVER_WORKERS: int = int(
    os.environ.get("WEB_CONCURRENCY", "0")
)  # 0 = auto (CPU count)
SERVER_THREADS: int = 4
SERVER_TIMEOUT: int = 30
SERVER_ACCESS_LOG: bool = True
SERVER_ACCESS_LOG_FIELDS: list[str] = [
    "method",
    "path",
    "query",
    "status",
    "duration_ms",
    "size",
    "ip",
    "user_agent",
    "referer",
]
SERVER_GRACEFUL_TIMEOUT: int = 30
# Idle timeout (seconds) for connections with no request in progress:
# HTTP/1.1 connections waiting for a request (first or keep-alive reuse)
# and HTTP/2 connections with no active streams. In-flight requests are
# never affected. Must exceed any fronting router/load balancer's
# connection reuse window so the router is always the side that closes an
# idle connection — it knows not to reuse one it's closing, while a
# server-side close races a request being written onto the connection
# (Heroku H13).
SERVER_KEEPALIVE_TIMEOUT: int = 300
SERVER_SENDFILE: bool = True
SERVER_CONNECTIONS: int = 1000
SERVER_H2_MAX_CONCURRENT_STREAMS: int = 100
SERVER_MAX_REQUESTS: int = 10000  # 0 = disabled
SERVER_MAX_REQUESTS_JITTER: int = 1000  # random variance to stagger restarts
# Largest request body the server accepts, enforced with a 413 on both
# HTTP/1.1 and HTTP/2. A declared Content-Length over the cap is
# rejected from the headers, before any of the body transfers; bodies
# with no declared length (chunked) are rejected the moment the received
# bytes exceed it, during ingest — always on bytes actually received,
# never on the declared length alone. This is a pre-auth allowance —
# what an anonymous client can make a worker receive and spool before
# any app code runs — so the default covers forms, images, and
# documents; raise it deliberately for larger uploads, or better, send
# large files direct to object storage (presigned URLs) instead of
# through the app server. None = no per-request cap of its own; the
# request is then limited only by the worker-wide
# SERVER_MAX_INFLIGHT_BODY_SIZE (a single body can never exceed the
# in-flight budget, so the worker enforces that bound as this cap and
# answers with the specific 413 instead of a 503). This is pure
# request-size policy, not a memory bound: bodies past
# SERVER_BODY_MAX_MEMORY_SIZE spool to an anonymous temp file.
SERVER_MAX_REQUEST_BODY_SIZE: int | None = 10485760  # i.e. 10 MB
# Request bodies are fully received before dispatch — in memory up to
# this size, spooling to an anonymous temp file beyond it (both
# protocols). Purely the RAM-vs-disk threshold, kept small because it
# bounds worst-case ingest memory at roughly this value times the
# concurrent request count. Per-write spool costs are microseconds
# (page cache); crossing the threshold pays a one-time rollover copy of
# this many bytes (~2ms at 1MB) on the event loop.
SERVER_BODY_MAX_MEMORY_SIZE: int = 1048576  # i.e. 1 MB
# Total in-flight request-body bytes (memory + disk spool) the worker
# holds across ALL connections. A request that would push past it gets a
# 503 — load shedding under an upload flood, bounding worst-case disk
# use no matter how many clients upload at once. None = no limit.
SERVER_MAX_INFLIGHT_BODY_SIZE: int | None = 1073741824  # i.e. 1 GB
# Minimum transfer rate (bytes/second) a client must sustain while the
# server is receiving a request body, after a short grace period for
# TCP slow-start. Inactivity timeouts alone can't stop a slow-drip body
# (R.U.D.Y.) — a client sending one byte per second stays "active"
# forever while pinning server resources. Only receive time counts
# (bodies are ingested before dispatch, so request processing can never
# trip it). Violations get a 408. 0 = disabled. Default matches
# Kestrel's MinRequestBodyDataRate.
SERVER_BODY_MIN_BYTES_PER_SECOND: int = 240

# MARK: Preflight Checks

# Silence checks by name
PREFLIGHT_SILENCED_CHECKS: list[str] = []

# Silence specific check results by id
PREFLIGHT_SILENCED_RESULTS: list[str] = []

# MARK: Shell

SHELL_IMPORT: str = ""
