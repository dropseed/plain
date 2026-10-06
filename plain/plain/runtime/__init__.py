import importlib.metadata
import os
import sys
import time
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

# The clock when this module was imported, and the CPU time the process had
# used by then. Importing this module is among the first things a `plain`
# command does, so a report on how long the process took to start (`plain
# test` prints one) counts from here. What came before it, the interpreter
# starting and Python's own imports, a process can't time; the CPU time is
# the nearest it has.
PLAIN_IMPORTED_AT = time.perf_counter()
CPU_SECONDS_BEFORE_PLAIN = time.process_time()

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

# Machine-level cache for downloaded binaries (Tailwind, Oxc, mkcert),
# shared across projects and checkouts.
if _cache_env := os.environ.get("PLAIN_CACHE_PATH"):
    PLAIN_CACHE_PATH = Path(_cache_env).expanduser()
elif _xdg_cache := os.environ.get("XDG_CACHE_HOME"):
    PLAIN_CACHE_PATH = Path(_xdg_cache).expanduser() / "plain"
else:
    PLAIN_CACHE_PATH = Path.home() / ".cache" / "plain"

# from plain.runtime import settings
settings = Settings()

_is_setup_complete = False


class AppPathNotFound(RuntimeError):
    pass


class SetupError(RuntimeError):
    pass


@dataclass(frozen=True, kw_only=True)
class SetupTiming:
    """
    How long each part of `setup()` took, so that a slow start can say
    which package's import it was. `plain test` prints it.
    """

    # Each `plain.setup` entry point by name, in the order run. plain.dev's
    # is where the `.env` files are read and the database is found.
    hooks: tuple[tuple[str, float], ...]
    # Configuring settings and logging. Reading the first setting is what
    # configures them, and imports `app/settings.py`.
    settings: float
    # Each installed package's import by name, in the order imported, with
    # everything the package imports in turn.
    package_imports: tuple[tuple[str, float], ...]
    # The packages' `ready()` methods, all together.
    ready: float


# What the one `setup()` took, once it has run.
setup_timing: SetupTiming | None = None


def setup() -> None:
    """
    Configure the settings (this happens as a side effect of accessing the
    first setting), configure logging and populate the app registry.
    """
    global _is_setup_complete, setup_timing

    if _is_setup_complete:
        raise SetupError(
            "Plain runtime is already set up. You can only call `setup()` once."
        )
    else:
        # Make sure we don't call setup() again
        _is_setup_complete = True

    # Packages can hook into the setup process through an entrypoint.
    hooks = []
    for entry_point in entry_points().select(group="plain.setup"):
        started = time.perf_counter()
        entry_point.load()()
        hooks.append((entry_point.name, time.perf_counter() - started))

    if not APP_PATH.exists():
        raise AppPathNotFound(
            "No app directory found. Are you sure you're in a Plain project?"
        )

    # Automatically put the project dir on the Python path
    # which doesn't otherwise happen when you run `plain` commands.
    # This makes "app.<module>" imports and relative imports work.
    if APP_PATH.parent.as_posix() not in sys.path:
        sys.path.insert(0, APP_PATH.parent.as_posix())

    started = time.perf_counter()
    configure_logging(
        plain_log_level=settings.FRAMEWORK_LOG_LEVEL,
        app_log_level=settings.LOG_LEVEL,
        app_log_format=settings.LOG_FORMAT,
        log_stream=settings.LOG_STREAM,
    )
    settings_seconds = time.perf_counter() - started

    packages_registry.populate(settings.INSTALLED_PACKAGES)

    setup_timing = SetupTiming(
        hooks=tuple(hooks),
        settings=settings_seconds,
        package_imports=tuple(packages_registry.import_seconds_by_package.items()),
        ready=packages_registry.ready_seconds,
    )


__all__ = [
    "APP_PATH",
    "CPU_SECONDS_BEFORE_PLAIN",
    "PLAIN_CACHE_PATH",
    "PLAIN_IMPORTED_AT",
    "PLAIN_TEMP_PATH",
    "AppPathNotFound",
    "Secret",
    "SetupError",
    "SetupTiming",
    "__version__",
    "settings",
    "setup",
    "setup_timing",
]
