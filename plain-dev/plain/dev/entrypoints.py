from importlib.util import find_spec
from pathlib import Path

from .dotenv import load_dotenv_files
from .utils import has_pyproject_toml


def setup() -> None:
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa
    from .services import auto_start_services

    has_postgres = find_spec("plain.postgres") is not None

    # `plain db` manages Postgres databases, so it only exists when
    # plain.postgres is installed.
    if has_postgres:
        from .db import cli  # noqa

    load_dotenv_files()

    # Resolve a database URL before services start, so DB-dependent services
    # inherit it. No-op when the user configured their own or when managed
    # Postgres is off; skipped entirely when plain.postgres isn't installed.
    if has_postgres:
        _ensure_managed_postgres()

    # Auto-start dev services for commands that need the runtime
    auto_start_services()


def _ensure_managed_postgres() -> None:
    # Located by walking up from the working directory: this runs before
    # settings are configured, so `APP_PATH` isn't available yet. `plain db`
    # walks up from the app instead and must land in the same place — see
    # `find_project_root`.
    from .postgres.identity import find_project_root

    project_root = find_project_root(Path.cwd())
    if not has_pyproject_toml(project_root):
        return

    from .postgres.resolve import ensure_postgres

    try:
        ensure_postgres(project_root)
    except Exception as e:
        # A database problem should surface when something actually needs the
        # database, with that command's own error — not as a failure of every
        # command that merely passed through setup().
        import click

        click.secho(f"Managed Postgres unavailable: {e}", fg="yellow", err=True)
