import sys
from pathlib import Path
from django.utils.version import get_version

VERSION = (5, 0, 0, "alpha", 0)

__version__ = get_version(VERSION)


def setup(set_prefix=True):
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    Set the thread-local urlresolvers script prefix if `set_prefix` is True.
    """
    from django.apps import apps
    from django.conf import settings
    from django.urls import set_script_prefix
    from django.utils.log import configure_logging

    # Automatically put the app dir on the Python path for convenience
    app_dir = Path.cwd() / "app"
    if app_dir.exists() and app_dir not in sys.path:
        sys.path.insert(0, app_dir.as_posix())

    configure_logging(settings.LOGGING_CONFIG, settings.LOGGING)

    if set_prefix:
        set_script_prefix("/")

    apps.populate(settings.INSTALLED_APPS)
