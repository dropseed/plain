import os

import click

from plain.cli.runtime import without_runtime_setup


def parse_workers(ctx: click.Context, param: click.Parameter, value: str) -> int:
    """Parse workers value - accepts int or 'auto' for CPU count."""
    if value == "auto":
        return os.cpu_count() or 1
    return int(value)


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
    type=int,
    default=1,
    help="Number of threads per worker",
    show_default=True,
)
@click.option(
    "--workers",
    "-w",
    type=str,
    default="1",
    envvar="WEB_CONCURRENCY",
    callback=parse_workers,
    help="Number of worker processes (or 'auto' for CPU count)",
    show_default=True,
)
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=30,
    help="Worker timeout in seconds",
    show_default=True,
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
    "--log-level",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error", "critical"]),
    help="Logging level",
    show_default=True,
)
@click.option(
    "--reload",
    is_flag=True,
    help="Restart workers when code changes (dev only)",
)
@click.option(
    "--access-log",
    default="-",
    help="Access log file (use '-' for stdout)",
    show_default=True,
)
@click.option(
    "--error-log",
    default="-",
    help="Error log file (use '-' for stderr)",
    show_default=True,
)
@click.option(
    "--log-format",
    default="%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
    help="Log format string (applies to both error and access logs)",
    show_default=True,
)
@click.option(
    "--access-log-format",
    help="Access log format string (HTTP request details)",
    default='%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"',
    show_default=True,
)
@click.option(
    "--max-requests",
    type=int,
    default=0,
    help="Max requests before worker restart (0=disabled)",
    show_default=True,
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
    log_level: str,
    reload: bool,
    access_log: str,
    error_log: str,
    log_format: str,
    access_log_format: str,
    max_requests: int,
    pidfile: str | None,
) -> None:
    """Production-ready WSGI server"""
    from plain.runtime import settings

    # Show settings loaded from environment
    if env_settings := settings.get_env_settings():
        click.secho("Settings from env:", dim=True)
        for name, defn in env_settings:
            click.secho(
                f"  {defn.env_var_name} -> {name}={defn.display_value()}", dim=True
            )

    from plain.server import ServerApplication
    from plain.server.config import Config

    cfg = Config(
        bind=list(bind),
        threads=threads,
        workers=workers,
        timeout=timeout,
        max_requests=max_requests,
        reload=reload,
        pidfile=pidfile,
        certfile=certfile,
        keyfile=keyfile,
        loglevel=log_level,
        accesslog=access_log,
        errorlog=error_log,
        log_format=log_format,
        access_log_format=access_log_format,
    )
    ServerApplication(cfg=cfg).run()
