import sys
from pathlib import Path

from bolt.utils.version import get_version

from .user_settings import LazySettings

VERSION = (5, 0, 0, "alpha", 0)

__version__ = get_version(VERSION)


# Made available without setup or settings
APP_PATH = Path.cwd() / "app"


# from bolt.runtime import settings
settings = LazySettings()


class AppPathNotFound(RuntimeError):
    pass


def setup():
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    """
    from bolt.env import dotenv
    from bolt.logs import configure_logging
    from bolt.packages import packages

    if not APP_PATH.exists():
        raise AppPathNotFound(
            "No app directory found. Are you sure you're in a Bolt project?"
        )

    # Automatically put the app dir on the Python path for convenience
    if APP_PATH not in sys.path:
        sys.path.insert(0, APP_PATH.as_posix())

    # Load .env files automatically before settings
    dotenv.load()

    configure_logging(settings.LOGGING)

    packages.populate(settings.INSTALLED_PACKAGES)


__all__ = [
    "setup",
    "settings",
    "APP_PATH",
    "VERSION",
    "__version__",
]
