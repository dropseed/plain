"""
Default Plain settings. Override these with settings in the module pointed to
by the PLAIN_SETTINGS_MODULE environment variable.
"""

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
HTTPS_REDIRECT_ENABLED = True

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
SECRET_KEY_FALLBACKS: Secret[list[str]] = []  # type: ignore[assignment]

# MARK: Internationalization

# Local time zone for this installation. All choices can be found here:
# https://en.wikipedia.org/wiki/List_of_tz_zones_by_name (although not all
# systems may support all possibilities). This is interpreted as the default
# user time zone.
TIME_ZONE: str = "UTC"

# Default charset to use for all Response objects, if a MIME type isn't
# manually specified. It's used to construct the Content-Type header.
DEFAULT_CHARSET = "utf-8"

# MARK: URL Configuration

# Whether to append trailing slashes to URLs.
APPEND_SLASH = True

# MARK: File Uploads

# List of upload handler classes to be applied in order.
FILE_UPLOAD_HANDLERS = [
    "plain.internal.files.uploadhandler.MemoryFileUploadHandler",
    "plain.internal.files.uploadhandler.TemporaryFileUploadHandler",
]

# Maximum size, in bytes, of a request before it will be streamed to the
# file system instead of into memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2621440  # i.e. 2.5 MB

# Maximum size in bytes of request data (excluding file uploads) that will be
# read before a SuspiciousOperationError400 (RequestDataTooBigError400) is raised.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2621440  # i.e. 2.5 MB

# Maximum number of GET/POST parameters that will be read before a
# SuspiciousOperationError400 (TooManyFieldsSentError400) is raised.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Maximum number of files encoded in a multipart upload that will be read
# before a SuspiciousOperationError400 (TooManyFilesSentError400) is raised.
DATA_UPLOAD_MAX_NUMBER_FILES = 100

# Directory in which upload streamed files will be temporarily saved. A value of
# `None` will make Plain use the operating system's default temporary directory
# (i.e. "/tmp" on *nix systems).
FILE_UPLOAD_TEMP_DIR = None

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

# MARK: Assets

# Whether to redirect the original asset path to the fingerprinted path.
ASSETS_REDIRECT_ORIGINAL = True

# If assets are served by a CDN, use this URL to prefix asset paths.
# Ex. "https://cdn.example.com/assets/"
ASSETS_BASE_URL: str = ""

# MARK: Preflight Checks

# Silence checks by name
PREFLIGHT_SILENCED_CHECKS: list[str] = []

# Silence specific check results by id
PREFLIGHT_SILENCED_RESULTS: list[str] = []

# MARK: Templates

TEMPLATES_JINJA_ENVIRONMENT = "plain.templates.jinja.DefaultEnvironment"

# MARK: Shell

SHELL_IMPORT: str = ""
