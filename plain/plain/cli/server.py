from __future__ import annotations

import os

import click

from plain.cli.options import SettingOption
from plain.cli.runtime import without_runtime_setup


@without_runtime_setup
@click.command()
@click.option(
    "--bind",
    "-b",
    multiple=True,
    default=["127.0.0.1:8000"],
    help="Address to bind to (HOST:PORT, can be used multiple times)",
)
@click.option(
    "--threads",
    type=click.IntRange(min=1),
    cls=SettingOption,
    setting="SERVER_THREADS",
    help="Number of threads per worker",
)
@click.option(
    "--workers",
    "-w",
    type=int,
    cls=SettingOption,
    setting="SERVER_WORKERS",
    help="Number of worker processes (0=auto, based on CPU count)",
)
@click.option(
    "--timeout",
    "-t",
    type=int,
    cls=SettingOption,
    setting="SERVER_TIMEOUT",
    help="Worker timeout in seconds",
)
@click.option(
    "--certfile",
    type=click.Path(exists=True),
    help="SSL certificate file",
)
@click.option(
    "--keyfile",
    type=click.Path(exists=True),
    help="SSL key file",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Restart workers when code changes (dev only)",
)
@click.option(
    "--access-log/--no-access-log",
    cls=SettingOption,
    setting="SERVER_ACCESS_LOG",
    help="Enable/disable access logging to stdout",
)
@click.option(
    "--max-requests",
    type=int,
    cls=SettingOption,
    setting="SERVER_MAX_REQUESTS",
    help="Max requests before worker restart (0=disabled)",
)
@click.option(
    "--pidfile",
    type=click.Path(),
    help="PID file path",
)
def server(
    bind: tuple[str, ...],
    threads: int,
    workers: int,
    timeout: int,
    certfile: str | None,
    keyfile: str | None,
    reload: bool,
    access_log: bool,
    max_requests: int,
    pidfile: str | None,
) -> None:
    """Production-ready HTTP server"""
    from plain.runtime import settings

    # Show settings loaded from environment
    if env_settings := settings.get_env_settings():
        click.secho("Settings from env:", dim=True)
        for name, defn in env_settings:
            click.secho(
                f"  {defn.env_var_name} -> {name}={defn.display_value()}", dim=True
            )

    # 0 = auto (CPU count)
    if workers == 0:
        workers = os.cpu_count() or 1

    from plain.server import ServerApplication

    ServerApplication(
        bind=list(bind),
        threads=threads,
        workers=workers,
        timeout=timeout,
        max_requests=max_requests,
        reload=reload,
        pidfile=pidfile,
        certfile=certfile,
        keyfile=keyfile,
        accesslog=access_log,
    ).run()
