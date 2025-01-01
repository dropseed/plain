import importlib.metadata
import sys
from importlib.metadata import entry_points
from pathlib import Path

from .user_settings import Settings

try:
    __version__ = importlib.metadata.version("plain")
except importlib.metadata.PackageNotFoundError:
    __version__ = "dev"


# Made available without setup or settings
APP_PATH = Path.cwd() / "app"

# from plain.runtime import settings
settings = Settings()


class AppPathNotFound(RuntimeError):
    pass


def setup():
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    """

    # Packages can hook into the setup process through an entrypoint.
    for entry_point in entry_points().select(group="plain.setup"):
        entry_point.load()()

    from plain.logs import configure_logging
    from plain.packages import packages

    if not APP_PATH.exists():
        raise AppPathNotFound(
            "No app directory found. Are you sure you're in a Plain project?"
        )

    # Automatically put the project dir on the Python path
    # which doesn't otherwise happen when you run `plain` commands.
    # This makes "app.<module>" imports and relative imports work.
    if APP_PATH.parent.as_posix() not in sys.path:
        sys.path.insert(0, APP_PATH.parent.as_posix())

    configure_logging(settings.LOGGING)

    packages.populate(settings.INSTALLED_PACKAGES)


__all__ = [
    "setup",
    "settings",
    "APP_PATH",
    "__version__",
]
