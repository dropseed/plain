import os
import subprocess
import sys
from importlib.metadata import entry_points

import click

from plain.cli import register_cli
from plain.cli.runtime import common_command
from plain.runtime import PLAIN_TEMP_PATH

from .alias import AliasManager
from .core import ENTRYPOINT_GROUP, DevSupervisor
from .services import ServicesSupervisor


@common_command
@register_cli("dev")
@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--port",
    "-p",
    default="",
    type=str,
    help=(
        "Port to run the web server on. "
        "If omitted, tries 8443 and picks the next free port."
    ),
)
@click.option(
    "--hostname",
    "-h",
    default=None,
    type=str,
    help="Hostname to run the web server on",
)
@click.option(
    "--log-level",
    "-l",
    default="",
    type=click.Choice(["debug", "info", "warning", "error", "critical", ""]),
    help="Log level",
)
@click.option(
    "--start",
    is_flag=True,
    default=False,
    help="Start in the background",
)
@click.option(
    "--stop",
    is_flag=True,
    default=False,
    help="Stop the background process",
)
@click.option(
    "--reinstall-ssl",
    is_flag=True,
    default=False,
    help="Reinstall SSL certificates (updates mkcert, reinstalls CA, regenerates certs)",
)
def cli(
    ctx: click.Context,
    port: str,
    hostname: str | None,
    log_level: str,
    start: bool,
    stop: bool,
    reinstall_ssl: bool,
) -> None:
    """Local development server"""
    if ctx.invoked_subcommand:
        return

    if start and stop:
        raise click.UsageError(
            "You cannot use both --start and --stop at the same time."
        )

    os.environ["DEV_SERVICES_AUTO"] = "false"

    dev = DevSupervisor()

    if stop:
        if ServicesSupervisor.running_pid():
            ServicesSupervisor().stop_process()
            click.secho("Services stopped.", fg="green")

        if not dev.running_pid():
            click.secho("No development server running.", fg="yellow")
            return

        dev.stop_process()
        click.secho("Development server stopped.", fg="green")
        return

    if running_pid := dev.running_pid():
        click.secho(dev.already_running_message(running_pid), fg="yellow")
        sys.exit(1)

    if start:
        extra_args = []
        if port:
            extra_args.extend(["--port", port])
        if hostname:
            extra_args.extend(["--hostname", hostname])
        if log_level:
            extra_args.extend(["--log-level", log_level])

        pid = DevSupervisor.spawn_background(*extra_args)
        click.secho(
            f"Development server started in the background (pid={pid}).",
            fg="green",
        )
        return

    # Check and prompt for alias setup
    AliasManager().check_and_prompt()

    dev.setup(
        port=int(port) if port else None,
        hostname=hostname,
        log_level=log_level if log_level else None,
    )
    returncode = dev.run(reinstall_ssl=reinstall_ssl)
    if returncode:
        sys.exit(returncode)


@cli.command()
@click.option("--start", is_flag=True, help="Start in the background")
@click.option("--stop", is_flag=True, help="Stop the background process")
def services(start: bool, stop: bool) -> None:
    """Start additional development services"""

    if start and stop:
        raise click.UsageError(
            "You cannot use both --start and --stop at the same time."
        )

    if stop:
        if not ServicesSupervisor.running_pid():
            click.secho("No services running.", fg="yellow")
            return
        ServicesSupervisor().stop_process()
        click.secho("Services stopped.", fg="green")
        return

    if running_pid := ServicesSupervisor.running_pid():
        click.secho(
            ServicesSupervisor.already_running_message(running_pid), fg="yellow"
        )
        sys.exit(1)

    if start:
        pid = ServicesSupervisor.spawn_background()
        click.secho(f"Services started in the background (pid={pid}).", fg="green")
        return

    ServicesSupervisor().run()


@cli.command()
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--pid", type=int, help="PID to show logs for")
@click.option("--path", is_flag=True, help="Output log file path")
@click.option("--services", is_flag=True, help="Show logs for services")
def logs(follow: bool, pid: int | None, path: bool, services: bool) -> None:
    """Show recent development logs"""

    if services:
        log_dir = PLAIN_TEMP_PATH / "dev" / "logs" / "services"
    else:
        log_dir = PLAIN_TEMP_PATH / "dev" / "logs" / "run"

    if pid:
        log_path = log_dir / f"{pid}.log"
        if not log_path.exists():
            click.secho(f"No log found for pid {pid}", fg="red")
            return
    else:
        logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
        if not logs:
            click.secho("No logs found", fg="yellow")
            return
        log_path = logs[-1]

    if path:
        click.echo(str(log_path))
        return

    if follow:
        subprocess.run(["tail", "-f", str(log_path)])
    else:
        with log_path.open() as f:
            click.echo(f.read())


@cli.command()
@click.option(
    "--list", "-l", "show_list", is_flag=True, help="List available entrypoints"
)
@click.argument("entrypoint", required=False)
def entrypoint(show_list: bool, entrypoint: str | None) -> None:
    """Run registered development entrypoints"""
    if not show_list and not entrypoint:
        raise click.UsageError("Please provide an entrypoint name or use --list")

    for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
        if show_list:
            click.echo(entry_point.name)
        elif entrypoint == entry_point.name:
            entry_point.load()()
