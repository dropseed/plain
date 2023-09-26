import sys
from pathlib import Path

from bolt.utils.version import get_version

from .user_settings import LazySettings

VERSION = (5, 0, 0, "alpha", 0)

__version__ = get_version(VERSION)


def setup():
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    """
    from bolt.env import dotenv
    from bolt.packages import packages
    from bolt.runtime import settings
    from bolt.utils.log import configure_logging

    # Automatically put the app dir on the Python path for convenience
    app_dir = Path.cwd() / "app"
    if app_dir.exists() and app_dir not in sys.path:
        sys.path.insert(0, app_dir.as_posix())

    dotenv.load()

    configure_logging(settings.LOGGING)

    packages.populate(settings.INSTALLED_PACKAGES)


# from bolt.runtime import settings
settings = LazySettings()


if (Path.cwd() / "app").exists():
    APP_PATH = Path.cwd() / "app"
else:
    APP_PATH = None


__all__ = [
    "setup",
    "settings",
    "APP_PATH",
    "VERSION",
    "__version__",
]
