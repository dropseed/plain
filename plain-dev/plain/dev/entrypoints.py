from importlib.util import find_spec
from pathlib import Path

from .dotenv import load_dotenv_files


def setup() -> None:
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa
    from .services import auto_start_services

    # `plain db` manages Postgres databases, so it only exists when
    # plain.postgres is installed.
    if find_spec("plain.postgres"):
        from .db import cli  # noqa

    load_dotenv_files()

    # Resolve a database URL before services start, so DB-dependent services
    # inherit it. No-op when the user configured their own, when managed
    # Postgres is off, or when plain.postgres isn't installed.
    _ensure_managed_postgres()

    # Auto-start dev services for commands that need the runtime
    auto_start_services()


def _find_project_root() -> Path | None:
    """Locate pyproject.toml without touching `plain.runtime`.

    This runs before settings are configured, so `APP_PATH` isn't available
    yet — walk up from the working directory instead.
    """
    for directory in [Path.cwd(), *Path.cwd().parents]:
        if (directory / "pyproject.toml").exists():
            return directory
    return None


def _ensure_managed_postgres() -> None:
    if not find_spec("plain.postgres"):
        return

    project_root = _find_project_root()
    if project_root is None:
        return

    from .postgres import ensure_postgres

    try:
        ensure_postgres(project_root)
    except Exception as e:
        # A database problem should surface when something actually needs the
        # database, with that command's own error — not as a failure of every
        # command that merely passed through setup().
        import click

        click.secho(f"Managed Postgres unavailable: {e}", fg="yellow", err=True)
