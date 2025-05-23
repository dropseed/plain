import importlib
import json
import multiprocessing
import os
import platform
import signal
import subprocess
import sys
import time
import tomllib
from importlib.metadata import entry_points
from importlib.util import find_spec
from pathlib import Path

import click
from rich.columns import Columns
from rich.console import Console
from rich.text import Text

from plain.cli import register_cli
from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .mkcert import MkcertManager
from .poncho.manager import Manager as PonchoManager
from .poncho.printer import Printer
from .services import Services, ServicesPid
from .utils import has_pyproject_toml

ENTRYPOINT_GROUP = "plain.dev"


@register_cli("dev")
@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--port",
    "-p",
    default=8443,
    type=int,
    help="Port to run the web server on",
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
def cli(ctx, port, hostname, log_level):
    """Start local development"""

    if ctx.invoked_subcommand:
        return

    if not hostname:
        project_name = os.path.basename(
            os.getcwd()
        )  # Use the directory name by default

        if has_pyproject_toml(APP_PATH.parent):
            with open(Path(APP_PATH.parent, "pyproject.toml"), "rb") as f:
                pyproject = tomllib.load(f)
                project_name = pyproject.get("project", {}).get("name", project_name)

        hostname = f"{project_name}.localhost"

    returncode = Dev(port=port, hostname=hostname, log_level=log_level).run()
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
def services():
    """Start additional services defined in pyproject.toml"""
    _services = Services()
    if _services.are_running():
        click.secho("Services already running", fg="yellow")
        return
    _services.run()


@cli.command()
@click.option(
    "--list", "-l", "show_list", is_flag=True, help="List available entrypoints"
)
@click.argument("entrypoint", required=False)
def entrypoint(show_list, entrypoint):
    """Entrypoints registered under plain.dev"""
    if not show_list and not entrypoint:
        click.secho("Please provide an entrypoint name or use --list", fg="red")
        sys.exit(1)

    for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
        if show_list:
            click.echo(entry_point.name)
        elif entrypoint == entry_point.name:
            entry_point.load()()


class Dev:
    def __init__(self, *, port, hostname, log_level):
        self.port = port
        self.hostname = hostname
        self.log_level = log_level

        self.ssl_key_path = None
        self.ssl_cert_path = None

        self.url = f"https://{self.hostname}:{self.port}"
        self.tunnel_url = os.environ.get("PLAIN_DEV_TUNNEL_URL", "")

        self.plain_env = {
            "PYTHONUNBUFFERED": "true",
            "PLAIN_DEV": "true",
            **os.environ,
        }

        if log_level:
            self.plain_env["PLAIN_LOG_LEVEL"] = log_level.upper()
            self.plain_env["APP_LOG_LEVEL"] = log_level.upper()

        self.custom_process_env = {
            **self.plain_env,
            "PORT": str(self.port),
            "PLAIN_DEV_URL": self.url,
        }

        if self.tunnel_url:
            status_bar = Columns(
                [
                    Text.from_markup(
                        f"[bold]Tunnel[/bold] [underline][link={self.tunnel_url}]{self.tunnel_url}[/link][/underline]"
                    ),
                    Text.from_markup(
                        f"[dim][bold]Server[/bold] [link={self.url}]{self.url}[/link][/dim]"
                    ),
                    Text.from_markup(
                        "[dim][bold]Ctrl+C[/bold] to stop[/dim]",
                        justify="right",
                    ),
                ],
                expand=True,
            )
        else:
            status_bar = Columns(
                [
                    Text.from_markup(
                        f"[bold]Server[/bold] [underline][link={self.url}]{self.url}[/link][/underline]"
                    ),
                    Text.from_markup(
                        "[dim][bold]Ctrl+C[/bold] to stop[/dim]", justify="right"
                    ),
                ],
                expand=True,
            )
        self.console = Console(markup=False, highlight=False)
        self.console_status = self.console.status(status_bar)

        self.poncho = PonchoManager(printer=Printer(lambda s: self.console.out(s)))

    def run(self):
        mkcert_manager = MkcertManager()
        mkcert_manager.setup_mkcert(install_path=Path.home() / ".plain" / "dev")
        self.ssl_cert_path, self.ssl_key_path = mkcert_manager.generate_certs(
            domain=self.hostname,
            storage_path=Path(PLAIN_TEMP_PATH) / "dev" / "certs",
        )

        self.symlink_plain_src()
        self.modify_hosts_file()
        self.set_allowed_hosts()
        self.run_preflight()

        # If we start services ourselves, we should manage the pidfile
        services_pid = None

        # Services start first (or are already running from a separate command)
        if Services.are_running():
            click.secho("Services already running", fg="yellow")
        elif services := Services.get_services(APP_PATH.parent):
            click.secho("\nStarting services...", italic=True, dim=True)
            services_pid = ServicesPid()
            services_pid.write()

            for name, data in services.items():
                env = {
                    **os.environ,
                    "PYTHONUNBUFFERED": "true",
                    **data.get("env", {}),
                }
                self.poncho.add_process(name, data["cmd"], env=env)

        # If plain.models is installed (common) then we
        # will do a couple extra things before starting all of the app-related
        # processes (this way they don't all have to db-wait or anything)
        process = None
        if find_spec("plain.models") is not None:
            # Use a custom signal to tell the main thread to add
            # the app processes once the db is ready
            signal.signal(signal.SIGUSR1, self.start_app)

            process = multiprocessing.Process(
                target=_process_task, args=(self.plain_env,)
            )
            process.start()

            # If there are no poncho processes, then let this process finish before
            # continuing (vs running in parallel)
            if self.poncho.num_processes() == 0:
                # Wait for the process to finish
                process.join()
        else:
            # Start the app processes immediately
            self.start_app(None, None)

        try:
            # Start processes we know about and block the main thread
            self.poncho.loop()

            # Remove the status bar
            self.console_status.stop()
        finally:
            # Make sure the services pid gets removed if we set it
            if services_pid:
                services_pid.rm()

            # Make sure the process is terminated if it is still running
            if process and process.is_alive():
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.join(timeout=3)
                if process.is_alive():
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.join()

        return self.poncho.returncode

    def start_app(self, signum, frame):
        # This runs in the main thread when SIGUSR1 is received
        # (or called directly if no thread).
        click.secho("\nStarting app...", italic=True, dim=True)

        # Manually start the status bar now so it isn't bungled by
        # another thread checking db stuff...
        self.console_status.start()

        self.add_gunicorn()
        self.add_entrypoints()
        self.add_pyproject_run()

    def symlink_plain_src(self):
        """Symlink the plain package into .plain so we can look at it easily"""
        plain_path = Path(
            importlib.util.find_spec("plain.runtime").origin
        ).parent.parent
        if not PLAIN_TEMP_PATH.exists():
            PLAIN_TEMP_PATH.mkdir()

        symlink_path = PLAIN_TEMP_PATH / "src"

        # The symlink is broken
        if symlink_path.is_symlink() and not symlink_path.exists():
            symlink_path.unlink()

        # The symlink exists but points to the wrong place
        if (
            symlink_path.is_symlink()
            and symlink_path.exists()
            and symlink_path.resolve() != plain_path
        ):
            symlink_path.unlink()

        if plain_path.exists() and not symlink_path.exists():
            symlink_path.symlink_to(plain_path)

    def modify_hosts_file(self):
        """Modify the hosts file to map the custom domain to 127.0.0.1."""
        entry_identifier = "# Added by plain"
        hosts_entry = f"127.0.0.1 {self.hostname}  {entry_identifier}"

        if platform.system() == "Windows":
            hosts_path = Path(r"C:\Windows\System32\drivers\etc\hosts")
            try:
                with hosts_path.open("r") as f:
                    content = f.read()

                if hosts_entry in content:
                    return  # Entry already exists; no action needed

                # Entry does not exist; add it
                with hosts_path.open("a") as f:
                    f.write(f"{hosts_entry}\n")
                click.secho(f"Added {self.hostname} to {hosts_path}", bold=True)
            except PermissionError:
                click.secho(
                    "Permission denied while modifying hosts file. Please run the script as an administrator.",
                    fg="red",
                )
                sys.exit(1)
        else:
            # For macOS and Linux
            hosts_path = Path("/etc/hosts")
            try:
                with hosts_path.open("r") as f:
                    content = f.read()

                if hosts_entry in content:
                    return  # Entry already exists; no action needed

                # Entry does not exist; append it using sudo
                click.secho(
                    f"Adding {self.hostname} to /etc/hosts file. You may be prompted for your password.\n",
                    bold=True,
                )
                cmd = f"echo '{hosts_entry}' | sudo tee -a {hosts_path} >/dev/null"
                subprocess.run(cmd, shell=True, check=True)
                click.secho(f"Added {self.hostname} to {hosts_path}\n", bold=True)
            except PermissionError:
                click.secho(
                    "Permission denied while accessing hosts file.",
                    fg="red",
                )
                sys.exit(1)
            except subprocess.CalledProcessError:
                click.secho(
                    "Failed to modify hosts file. Please ensure you have sudo privileges.",
                    fg="red",
                )
                sys.exit(1)

    def set_allowed_hosts(self):
        if "PLAIN_ALLOWED_HOSTS" not in os.environ:
            hostnames = [self.hostname]
            if self.tunnel_url:
                # Add the tunnel URL to the allowed hosts
                hostnames.append(self.tunnel_url.split("://")[1])
            allowed_hosts = json.dumps(hostnames)
            self.plain_env["PLAIN_ALLOWED_HOSTS"] = allowed_hosts
            self.custom_process_env["PLAIN_ALLOWED_HOSTS"] = allowed_hosts
            click.secho(
                f"Automatically set PLAIN_ALLOWED_HOSTS={allowed_hosts}", dim=True
            )

    def run_preflight(self):
        click.echo()
        if subprocess.run(["plain", "preflight"], env=self.plain_env).returncode:
            click.secho("Preflight check failed!", fg="red")
            sys.exit(1)

    def add_gunicorn(self):
        # Watch .env files for reload
        extra_watch_files = []
        for f in os.listdir(APP_PATH.parent):
            if f.startswith(".env"):
                # Needs to be absolute or "./" for inotify to work on Linux...
                # https://github.com/dropseed/plain/issues/26
                extra_watch_files.append(str(Path(APP_PATH.parent) / f))

        reload_extra = " ".join(f"--reload-extra-file {f}" for f in extra_watch_files)
        gunicorn_cmd = [
            "gunicorn",
            "--bind",
            f"{self.hostname}:{self.port}",
            "--certfile",
            str(self.ssl_cert_path),
            "--keyfile",
            str(self.ssl_key_path),
            "--threads",
            "4",
            "--reload",
            "plain.wsgi:app",
            "--timeout",
            "60",
            "--log-level",
            self.log_level or "info",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            *reload_extra.split(),
            "--access-logformat",
            "'\"%(r)s\" status=%(s)s length=%(b)s time=%(M)sms'",
            "--log-config-json",
            str(Path(__file__).parent / "gunicorn_logging.json"),
        ]
        gunicorn = " ".join(gunicorn_cmd)

        self.poncho.add_process("plain", gunicorn, env=self.plain_env)

    def add_entrypoints(self):
        for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
            self.poncho.add_process(
                entry_point.name,
                f"plain dev entrypoint {entry_point.name}",
                env=self.plain_env,
            )

    def add_pyproject_run(self):
        """Additional processes that only run during `plain dev`."""
        if not has_pyproject_toml(APP_PATH.parent):
            return

        with open(Path(APP_PATH.parent, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)

        run_commands = (
            pyproject.get("tool", {}).get("plain", {}).get("dev", {}).get("run", {})
        )
        for name, data in run_commands.items():
            env = {
                **self.custom_process_env,
                **data.get("env", {}),
            }
            self.poncho.add_process(name, data["cmd"], env=env)


def _process_task(env):
    # Make this process the leader of a new group which can be killed together if it doesn't finish
    os.setsid()

    subprocess.run(["plain", "models", "db-wait"], env=env, check=True)
    subprocess.run(["plain", "migrate", "--backup"], env=env, check=True)

    # preflight with db?

    # Send SIGUSR1 to the parent process so the parent's handler is invoked
    os.kill(os.getppid(), signal.SIGUSR1)
