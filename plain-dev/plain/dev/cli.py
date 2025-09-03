import os
import subprocess
import sys
import time
from importlib.metadata import entry_points

import click

from plain.cli import register_cli
from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .core import ENTRYPOINT_GROUP, DevProcess
from .services import ServicesProcess


class DevGroup(click.Group):
    """Custom group that ensures *services* are running on CLI startup."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._auto_start_services()

    @staticmethod
    def _auto_start_services():
        """Start dev *services* in the background if not already running."""

        # Check if we're in CI and auto-start is not explicitly enabled
        if os.environ.get("CI") and os.environ.get("PLAIN_DEV_SERVICES_AUTO") is None:
            return

        if os.environ.get("PLAIN_DEV_SERVICES_AUTO", "true") not in [
            "1",
            "true",
            "yes",
        ]:
            return

        # Don't do anything if it looks like a "services" command is being run explicitly
        if "dev" in sys.argv:
            if "logs" in sys.argv or "services" in sys.argv or "--stop" in sys.argv:
                return

        if not ServicesProcess.get_services(APP_PATH.parent):
            return

        if ServicesProcess.running_pid():
            return

        click.secho(
            "Starting background dev services (terminate with `plain dev --stop`)...",
            dim=True,
        )

        subprocess.Popen(
            [sys.executable, "-m", "plain", "dev", "services", "--start"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Give services time to start and retry the check
        wait_times = [0.5, 1, 1]  # First check at 0.5s, then 1s intervals
        for wait_time in wait_times:
            time.sleep(wait_time)
            if ServicesProcess.running_pid():
                return  # Services started successfully

        # Only show error after multiple attempts
        if not ServicesProcess.running_pid():
            click.secho(
                "Failed to start dev services. Here are the logs:",
                fg="red",
            )
            subprocess.run(
                ["plain", "dev", "logs", "--services"],
                check=False,
            )
            sys.exit(1)


@register_cli("dev")
@click.group(cls=DevGroup, invoke_without_command=True)
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
def cli(ctx, port, hostname, log_level, start, stop):
    """Start local development"""

    if ctx.invoked_subcommand:
        return

    if start and stop:
        raise click.UsageError(
            "You cannot use both --start and --stop at the same time."
        )

    os.environ["PLAIN_DEV_SERVICES_AUTO"] = "false"

    dev = DevProcess()

    if stop:
        if ServicesProcess.running_pid():
            ServicesProcess().stop_process()
            click.secho("Services stopped.", fg="green")

        if not dev.running_pid():
            click.secho("No development server running.", fg="yellow")
            return

        dev.stop_process()
        click.secho("Development server stopped.", fg="green")
        return

    if running_pid := dev.running_pid():
        click.secho(f"`plain dev` already running (pid={running_pid})", fg="yellow")
        sys.exit(1)

    if start:
        args = [sys.executable, "-m", "plain", "dev"]
        if port:
            args.extend(["--port", port])
        if hostname:
            args.extend(["--hostname", hostname])
        if log_level:
            args.extend(["--log-level", log_level])

        result = subprocess.Popen(
            args=args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        click.secho(
            f"Development server started in the background (pid={result.pid}).",
            fg="green",
        )
        return

    dev.setup(port=port, hostname=hostname, log_level=log_level)
    returncode = dev.run()
    if returncode:
        sys.exit(returncode)


@cli.command()
def debug():
    """Connect to the remote debugger"""

    def _connect():
        if subprocess.run(["which", "nc"], capture_output=True).returncode == 0:
            return subprocess.run(["nc", "-C", "localhost", "4444"])
        else:
            raise OSError("nc not found")

    result = _connect()

    # Try again once without a message
    if result.returncode == 1:
        time.sleep(1)
        result = _connect()

    # Keep trying...
    while result.returncode == 1:
        click.secho(
            "Failed to connect. Make sure remote pdb is ready. Retrying...", fg="red"
        )
        result = _connect()
        time.sleep(1)


@cli.command()
@click.option("--start", is_flag=True, help="Start in the background")
@click.option("--stop", is_flag=True, help="Stop the background process")
def services(start, stop):
    """Start additional services defined in pyproject.toml"""

    if start and stop:
        raise click.UsageError(
            "You cannot use both --start and --stop at the same time."
        )

    if stop:
        if not ServicesProcess.running_pid():
            click.secho("No services running.", fg="yellow")
            return
        ServicesProcess().stop_process()
        click.secho("Services stopped.", fg="green")
        return

    if running_pid := ServicesProcess.running_pid():
        click.secho(f"Services already running (pid={running_pid})", fg="yellow")
        sys.exit(1)

    if start:
        result = subprocess.Popen(
            args=[sys.executable, "-m", "plain", "dev", "services"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        click.secho(
            f"Services started in the background (pid={result.pid}).", fg="green"
        )
        return

    ServicesProcess().run()


@cli.command()
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--pid", type=int, help="PID to show logs for")
@click.option("--path", is_flag=True, help="Output log file path")
@click.option("--services", is_flag=True, help="Show logs for services")
def logs(follow, pid, path, services):
    """Show logs from recent plain dev runs."""

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
def entrypoint(show_list, entrypoint):
    """Entrypoints registered under plain.dev"""
    if not show_list and not entrypoint:
        raise click.UsageError("Please provide an entrypoint name or use --list")

    for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
        if show_list:
            click.echo(entry_point.name)
        elif entrypoint == entry_point.name:
            entry_point.load()()
