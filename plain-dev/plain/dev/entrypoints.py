from pathlib import Path

from .dotenv import load_dotenv_files


def setup() -> None:
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa
    from .db import cli  # noqa
    from .services import auto_start_services

    load_dotenv_files()

    # Ensure managed Postgres (container + per-checkout DB) and inject the URL
    # BEFORE services start, so DB-dependent services inherit it. No-op when a
    # URL is already configured (BYO) or plain.postgres isn't installed.
    _ensure_managed_postgres()

    # Auto-start dev services for commands that need the runtime
    auto_start_services()


def _ensure_managed_postgres() -> None:
    import sys
    from importlib.util import find_spec

    # Only for commands that actually need the database/runtime (mirrors
    # auto_start_services). `plain db` self-ensures, so it's not listed here.
    runtime_commands = {
        "postgres",
        "dev",
        "migrations",
        "preflight",
        "request",
        "run",
        "shell",
        "test",
    }
    if not (runtime_commands & set(sys.argv)):
        return
    if not find_spec("plain.postgres"):
        return

    # Find the project root WITHOUT touching plain.runtime — this runs before
    # settings are configured. cwd holds the pyproject.toml when running `plain`.
    project_root = next(
        (
            d
            for d in [Path.cwd(), *Path.cwd().parents]
            if (d / "pyproject.toml").exists()
        ),
        None,
    )
    if project_root is None:
        return

    try:
        from .postgres import ensure_postgres

        ensure_postgres(project_root)
    except Exception as e:  # prototype: never block the command on this
        import click

        click.secho(f"Managed Postgres skipped: {e}", fg="yellow", err=True)
