import importlib.metadata
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Self

from plain.logs.configure import configure_logging
from plain.packages import packages_registry

from .secret import Secret
from .user_settings import Settings

try:
    __version__ = importlib.metadata.version("plain")
except importlib.metadata.PackageNotFoundError:
    __version__ = "dev"


# Made available without setup or settings
APP_PATH = Path.cwd() / "app"
PLAIN_TEMP_PATH = Path.cwd() / ".plain"

# from plain.runtime import settings
settings = Settings()

_is_setup_complete = False


class AppPathNotFound(RuntimeError):
    pass


class SetupError(RuntimeError):
    pass


def setup() -> None:
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    """
    global _is_setup_complete

    if _is_setup_complete:
        raise SetupError(
            "Plain runtime is already set up. You can only call `setup()` once."
        )
    else:
        # Make sure we don't call setup() again
        _is_setup_complete = True

    # Packages can hook into the setup process through an entrypoint.
    for entry_point in entry_points().select(group="plain.setup"):
        entry_point.load()()

    if not APP_PATH.exists():
        raise AppPathNotFound(
            "No app directory found. Are you sure you're in a Plain project?"
        )

    # Automatically put the project dir on the Python path
    # which doesn't otherwise happen when you run `plain` commands.
    # This makes "app.<module>" imports and relative imports work.
    if APP_PATH.parent.as_posix() not in sys.path:
        sys.path.insert(0, APP_PATH.parent.as_posix())

    configure_logging(
        plain_log_level=settings.FRAMEWORK_LOG_LEVEL,
        app_log_level=settings.LOG_LEVEL,
        app_log_format=settings.LOG_FORMAT,
        log_stream=settings.LOG_STREAM,
    )

    packages_registry.populate(settings.INSTALLED_PACKAGES)


class SettingsReference(str):
    """
    String subclass which references a current settings value. It's treated as
    the value in memory but serializes to a settings.NAME attribute reference.
    """

    def __new__(self, setting_name: str) -> Self:
        value = getattr(settings, setting_name)
        return str.__new__(self, value)

    def __init__(self, setting_name: str):
        self.setting_name = setting_name


__all__ = [
    "setup",
    "settings",
    "Secret",
    "SettingsReference",
    "APP_PATH",
    "__version__",
]
