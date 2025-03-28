"""
Default Plain settings. Override these with settings in the module pointed to
by the PLAIN_SETTINGS_MODULE environment variable.
"""

from pathlib import Path

from plain.runtime import APP_PATH as default_app_path

####################
# CORE             #
####################

DEBUG: bool = False

PLAIN_TEMP_PATH: Path = default_app_path.parent / ".plain"

# Hosts/domain names that are valid for this site.
# "*" matches anything, ".example.com" matches example.com and all subdomains
ALLOWED_HOSTS: list[str] = []

# Local time zone for this installation. All choices can be found here:
# https://en.wikipedia.org/wiki/List_of_tz_zones_by_name (although not all
# systems may support all possibilities). This is interpreted as the default
# user time zone.
TIME_ZONE: str = "UTC"

# Default charset to use for all Response objects, if a MIME type isn't
# manually specified. It's used to construct the Content-Type header.
DEFAULT_CHARSET = "utf-8"

# List of strings representing installed packages.
INSTALLED_PACKAGES: list[str] = []

# Whether to append trailing slashes to URLs.
APPEND_SLASH = True

# Default headers for all responses.
DEFAULT_RESPONSE_HEADERS = {
    # "Content-Security-Policy": "default-src 'self'",
    # https://hstspreload.org/
    # "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

# Whether to redirect all non-HTTPS requests to HTTPS.
HTTPS_REDIRECT_ENABLED = True
HTTPS_REDIRECT_EXEMPT = []
HTTPS_REDIRECT_HOST = None

# If your Plain app is behind a proxy that sets a header to specify secure
# connections, AND that proxy ensures that user-submitted headers with the
# same name are ignored (so that people can't spoof it), set this value to
# a tuple of (header_name, header_value). For any requests that come in with
# that header/value, request.is_https() will return True.
# WARNING! Only set this if you fully understand what you're doing. Otherwise,
# you may be opening yourself up to a security risk.
HTTPS_PROXY_HEADER = None

# Whether to use the X-Forwarded-Host and X-Forwarded-Port headers
# when determining the host and port for the request.
USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = False

# A secret key for this particular Plain installation. Used in secret-key
# hashing algorithms. Set this in your settings, or Plain will complain
# loudly.
SECRET_KEY: str

# List of secret keys used to verify the validity of signatures. This allows
# secret key rotation.
SECRET_KEY_FALLBACKS: list[str] = []

URLS_ROUTER: str

# List of upload handler classes to be applied in order.
FILE_UPLOAD_HANDLERS = [
    "plain.internal.files.uploadhandler.MemoryFileUploadHandler",
    "plain.internal.files.uploadhandler.TemporaryFileUploadHandler",
]

# Maximum size, in bytes, of a request before it will be streamed to the
# file system instead of into memory.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2621440  # i.e. 2.5 MB

# Maximum size in bytes of request data (excluding file uploads) that will be
# read before a SuspiciousOperation (RequestDataTooBig) is raised.
DATA_UPLOAD_MAX_MEMORY_SIZE = 2621440  # i.e. 2.5 MB

# Maximum number of GET/POST parameters that will be read before a
# SuspiciousOperation (TooManyFieldsSent) is raised.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Maximum number of files encoded in a multipart upload that will be read
# before a SuspiciousOperation (TooManyFilesSent) is raised.
DATA_UPLOAD_MAX_NUMBER_FILES = 100

# Directory in which upload streamed files will be temporarily saved. A value of
# `None` will make Plain use the operating system's default temporary directory
# (i.e. "/tmp" on *nix systems).
FILE_UPLOAD_TEMP_DIR = None

# User-defined overrides for error views by status code
HTTP_ERROR_VIEWS: dict[int] = {}

##############
# MIDDLEWARE #
##############

# List of middleware to use. Order is important; in the request phase, these
# middleware will be applied in the order given, and in the response
# phase the middleware will be applied in reverse order.
MIDDLEWARE: list[str] = []

###########
# SIGNING #
###########

COOKIE_SIGNING_BACKEND = "plain.signing.TimestampSigner"

########
# CSRF #
########

# Settings for CSRF cookie.
CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_AGE = 60 * 60 * 24 * 7 * 52  # 1 year
CSRF_COOKIE_DOMAIN = None
CSRF_COOKIE_PATH = "/"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "CSRF-Token"
CSRF_POST_NAME = "_csrftoken"
CSRF_TRUSTED_ORIGINS: list[str] = []

###########
# LOGGING #
###########

# Custom logging configuration.
LOGGING = {}

###############
# ASSETS #
###############

# Whether to redirect the original asset path to the fingerprinted path.
ASSETS_REDIRECT_ORIGINAL = True

# If assets are served by a CDN, use this URL to prefix asset paths.
# Ex. "https://cdn.example.com/assets/"
ASSETS_BASE_URL: str = ""

####################
# PREFLIGHT CHECKS #
####################

# List of all issues generated by system checks that should be silenced. Light
# issues like warnings, infos or debugs will not generate a message. Silencing
# serious issues like errors and criticals does not result in hiding the
# message, but Plain will not stop you from e.g. running server.
PREFLIGHT_SILENCED_CHECKS = []

#############
# Templates #
#############

TEMPLATES_JINJA_ENVIRONMENT = "plain.templates.jinja.DefaultEnvironment"

#########
# Shell #
#########

SHELL_IMPORT: str = ""
