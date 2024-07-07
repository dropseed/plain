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
# systems may support all possibilities). When USE_TZ is True, this is
# interpreted as the default user time zone.
TIME_ZONE = "America/Chicago"

# If you set this to True, Plain will use timezone-aware datetimes.
USE_TZ = True

# Default charset to use for all Response objects, if a MIME type isn't
# manually specified. It's used to construct the Content-Type header.
DEFAULT_CHARSET = "utf-8"

# List of strings representing installed packages.
INSTALLED_PACKAGES: list = []

# Whether to append trailing slashes to URLs.
APPEND_SLASH = True

# A secret key for this particular Plain installation. Used in secret-key
# hashing algorithms. Set this in your settings, or Plain will complain
# loudly.
SECRET_KEY: str

# List of secret keys used to verify the validity of signatures. This allows
# secret key rotation.
SECRET_KEY_FALLBACKS: list[str] = []

ROOT_URLCONF = "urls"

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

# The numeric mode to set newly-uploaded files to. The value should be a mode
# you'd pass directly to os.chmod; see
# https://docs.python.org/library/os.html#files-and-directories.
FILE_UPLOAD_PERMISSIONS = 0o644

# The numeric mode to assign to newly-created directories, when uploading files.
# The value should be a mode as you'd pass to os.chmod;
# see https://docs.python.org/library/os.html#files-and-directories.
FILE_UPLOAD_DIRECTORY_PERMISSIONS = None

# Default X-Frame-Options header value
X_FRAME_OPTIONS = "DENY"

USE_X_FORWARDED_HOST = False
USE_X_FORWARDED_PORT = False

# User-defined overrides for error views by status code
HTTP_ERROR_VIEWS: dict[int] = {}

# If your Plain app is behind a proxy that sets a header to specify secure
# connections, AND that proxy ensures that user-submitted headers with the
# same name are ignored (so that people can't spoof it), set this value to
# a tuple of (header_name, header_value). For any requests that come in with
# that header/value, request.is_secure() will return True.
# WARNING! Only set this if you fully understand what you're doing. Otherwise,
# you may be opening yourself up to a security risk.
SECURE_PROXY_SSL_HEADER = None

##############
# MIDDLEWARE #
##############

# List of middleware to use. Order is important; in the request phase, these
# middleware will be applied in the order given, and in the response
# phase the middleware will be applied in reverse order.
MIDDLEWARE = [
    "plain.middleware.security.SecurityMiddleware",
    "plain.assets.whitenoise.middleware.WhiteNoiseMiddleware",
    "plain.middleware.common.CommonMiddleware",
    "plain.csrf.middleware.CsrfViewMiddleware",
    "plain.middleware.clickjacking.XFrameOptionsMiddleware",
]

###########
# SIGNING #
###########

SIGNING_BACKEND = "plain.signing.TimestampSigner"

########
# CSRF #
########

# Settings for CSRF cookie.
CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_AGE = 60 * 60 * 24 * 7 * 52
CSRF_COOKIE_DOMAIN = None
CSRF_COOKIE_PATH = "/"
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"
CSRF_TRUSTED_ORIGINS: list[str] = []
CSRF_USE_SESSIONS = False

###########
# LOGGING #
###########

# Custom logging configuration.
LOGGING = {}

###############
# ASSETS #
###############

ASSETS_BACKEND = "plain.assets.whitenoise.storage.CompressedManifestStaticFilesStorage"

# List of finder classes that know how to find assets files in
# various locations.
ASSETS_FINDERS = [
    "plain.assets.finders.FileSystemFinder",
    "plain.assets.finders.PackageDirectoriesFinder",
]

# Absolute path to the directory assets files should be collected to.
# Example: "/var/www/example.com/assets/"
ASSETS_ROOT = PLAIN_TEMP_PATH / "assets_collected"

# URL that handles the assets files served from ASSETS_ROOT.
# Example: "http://example.com/assets/", "http://assets.example.com/"
ASSETS_URL = "/assets/"

####################
# PREFLIGHT CHECKS #
####################

# List of all issues generated by system checks that should be silenced. Light
# issues like warnings, infos or debugs will not generate a message. Silencing
# serious issues like errors and criticals does not result in hiding the
# message, but Plain will not stop you from e.g. running server.
SILENCED_PREFLIGHT_CHECKS = []

#######################
# SECURITY MIDDLEWARE #
#######################
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_HSTS_SECONDS = 0
SECURE_REDIRECT_EXEMPT = []
SECURE_REFERRER_POLICY = "same-origin"
SECURE_SSL_HOST = None
SECURE_SSL_REDIRECT = False

#############
# Templates #
#############

JINJA_LOADER = "jinja2.loaders.FileSystemLoader"
JINJA_ENVIRONMENT = "plain.templates.jinja.defaults.create_default_environment"
