import importlib.metadata
import sys
from os import environ
from pathlib import Path

from dotenv import load_dotenv

from .user_settings import LazySettings

try:
    __version__ = importlib.metadata.version("plain")
except importlib.metadata.PackageNotFoundError:
    __version__ = "dev"


# Made available without setup or settings
APP_PATH = Path.cwd() / "app"


# from plain.runtime import settings
settings = LazySettings()


class AppPathNotFound(RuntimeError):
    pass


def setup():
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    """
    from plain.logs import configure_logging
    from plain.packages import packages

    if not APP_PATH.exists():
        raise AppPathNotFound(
            "No app directory found. Are you sure you're in a Plain project?"
        )

    # Automatically put the app dir on the Python path for convenience
    if APP_PATH not in sys.path:
        sys.path.insert(0, APP_PATH.as_posix())

    # Load .env files automatically before settings
    if app_env := environ.get("PLAIN_ENV", ""):
        load_dotenv(f".env.{app_env}")
    else:
        load_dotenv(".env")

    configure_logging(settings.LOGGING)

    packages.populate(settings.INSTALLED_PACKAGES)


__all__ = [
    "setup",
    "settings",
    "APP_PATH",
    "__version__",
]
