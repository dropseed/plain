import hashlib
import importlib.metadata
import os
import sys
from importlib.metadata import entry_points
from pathlib import Path

from plain.logs.configure import configure_logging
from plain.packages import packages_registry

from .secret import Secret
from .user_settings import Settings

try:
    __version__ = importlib.metadata.version("plain")
except importlib.metadata.PackageNotFoundError:
    __version__ = "dev"


def find_project_root(start: Path) -> Path:
    """The nearest directory at or above `start` holding a pyproject.toml.

    One definition, used by `setup()` (which starts from the working
    directory), the CLI (which starts from the app), and the dev supervisors,
    because they have to agree: the project root decides where a checkout's
    `.plain` lives and where its state is keyed. Two answers means two
    checkouts.
    """
    for directory in [start, *start.parents]:
        if (directory / "pyproject.toml").exists():
            return directory
    return start


# Made available without setup or settings
APP_PATH = Path.cwd() / "app"
PLAIN_TEMP_PATH = find_project_root(Path.cwd()) / ".plain"

# Machine-level cache for downloaded binaries (Tailwind, Oxc, mkcert),
# shared across projects and checkouts.
if _cache_env := os.environ.get("PLAIN_CACHE_PATH"):
    PLAIN_CACHE_PATH = Path(_cache_env).expanduser()
elif _xdg_cache := os.environ.get("XDG_CACHE_HOME"):
    PLAIN_CACHE_PATH = Path(_xdg_cache).expanduser() / "plain"
else:
    PLAIN_CACHE_PATH = Path.home() / ".cache" / "plain"


def checkout_id(project_root: Path) -> str:
    """What "this checkout" means when we record or compare ownership.

    One definition because it's compared for exact equality against facts
    recorded elsewhere, and two sites normalizing differently would silently
    disagree forever rather than fail.
    """
    return str(project_root.resolve())


def checkout_state_path(project_root: Path) -> Path:
    """Where this checkout's facts about itself are kept.

    A working tree is exactly what gets symlinked, copied, rsynced, and
    mounted into containers, so state keyed by location (like `.plain`) is
    eventually read by the wrong reader — two checkouts sharing one `.plain`
    would quietly share a database, or one would refuse to start because the
    other's dev server holds the pidfile. So a checkout's facts (as opposed to
    artifacts like logs or compiled assets, which do belong in `.plain`) are
    kept here instead, keyed by the checkout's resolved path, with the
    readable checkout name in the directory too so the cache stays greppable.
    """
    resolved = project_root.resolve()
    sanitized_name = "".join(
        c if c.isalnum() else "_" for c in resolved.name.lower()
    ).strip("_")
    digest = hashlib.sha256(str(resolved).encode()).hexdigest()[:8]
    return PLAIN_CACHE_PATH / "checkouts" / f"{sanitized_name}-{digest}"


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


__all__ = [
    "APP_PATH",
    "PLAIN_CACHE_PATH",
    "PLAIN_TEMP_PATH",
    "AppPathNotFound",
    "Secret",
    "SetupError",
    "__version__",
    "checkout_id",
    "checkout_state_path",
    "find_project_root",
    "settings",
    "setup",
]
