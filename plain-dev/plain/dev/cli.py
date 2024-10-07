import json
import os
import platform
import subprocess
import sys
from importlib.metadata import entry_points
from importlib.util import find_spec
from pathlib import Path

import click
import tomllib

from plain.runtime import APP_PATH, settings

from .db import cli as db_cli
from .mkcert import MkcertManager
from .pid import Pid
from .poncho.manager import Manager as PonchoManager
from .services import Services
from .utils import has_pyproject_toml

ENTRYPOINT_GROUP = "plain.dev"


@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--port",
    "-p",
    default=8443,
    type=int,
    help="Port to run the web server on",
    envvar="PORT",
)
def cli(ctx, port):
    """Start local development"""

    if ctx.invoked_subcommand:
        return

    returncode = Dev(port=port).run()
    if returncode:
        sys.exit(returncode)


@cli.command()
def services():
    """Start additional services defined in pyproject.toml"""
    Services().run()


@cli.command()
@click.option(
    "--list", "-l", "show_list", is_flag=True, help="List available entrypoints"
)
@click.argument("entrypoint", required=False)
def entrypoint(show_list, entrypoint):
    f"""Entrypoints registered under {ENTRYPOINT_GROUP}"""
    if not show_list and not entrypoint:
        click.secho("Please provide an entrypoint name or use --list", fg="red")
        sys.exit(1)

    for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
        if show_list:
            click.echo(entry_point.name)
        elif entrypoint == entry_point.name:
            entry_point.load()()


class Dev:
    def __init__(self, *, port):
        self.poncho = PonchoManager()
        self.port = port
        self.plain_env = {
            **os.environ,
            "PYTHONUNBUFFERED": "true",
        }
        self.custom_process_env = {
            **self.plain_env,
            "PORT": str(self.port),
            "PYTHONPATH": os.path.join(APP_PATH.parent, "app"),
        }
        self.project_name = os.path.basename(os.getcwd())
        self.domain = f"{self.project_name}.localhost"
        self.ssl_cert_path = None
        self.ssl_key_path = None

    def run(self):
        pid = Pid()
        pid.write()

        try:
            mkcert_manager = MkcertManager()
            mkcert_manager.setup_mkcert(install_path=Path.home() / ".plain" / "dev")
            self.ssl_cert_path, self.ssl_key_path = mkcert_manager.generate_certs(
                domain=self.domain,
                storage_path=Path(settings.PLAIN_TEMP_PATH) / "dev" / "certs",
            )
            self.modify_hosts_file()
            self.set_csrf_trusted_origins()
            self.set_allowed_hosts()
            self.run_preflight()

            # Processes for poncho to run simultaneously
            self.add_gunicorn()
            self.add_entrypoints()
            self.add_pyproject_run()
            self.add_services()

            # Output the clickable link before starting the manager loop
            url = f"https://{self.domain}:{self.port}/"
            click.secho(
                f"\nYour application is running at: {click.style(url, fg='green', underline=True)}\n",
                bold=True,
            )

            self.poncho.loop()

            return self.poncho.returncode
        finally:
            pid.rm()

    def modify_hosts_file(self):
        """Modify the hosts file to map the custom domain to 127.0.0.1."""
        entry_identifier = "# Added by plain"
        hosts_entry = f"127.0.0.1 {self.domain}  {entry_identifier}"

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
                click.secho(f"Added {self.domain} to {hosts_path}", bold=True)
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
                    "Modifying /etc/hosts file. You may be prompted for your password.",
                    bold=True,
                )
                cmd = f"echo '{hosts_entry}' | sudo tee -a {hosts_path} >/dev/null"
                subprocess.run(cmd, shell=True, check=True)
                click.secho(f"Added {self.domain} to {hosts_path}", bold=True)
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

    def set_csrf_trusted_origins(self):
        csrf_trusted_origins = json.dumps(
            [
                f"https://{self.domain}:{self.port}",
            ]
        )

        click.secho(
            f"Automatically set PLAIN_CSRF_TRUSTED_ORIGINS={click.style(csrf_trusted_origins, underline=True)}",
            bold=True,
        )

        # Set environment variables
        self.plain_env["PLAIN_CSRF_TRUSTED_ORIGINS"] = csrf_trusted_origins
        self.custom_process_env["PLAIN_CSRF_TRUSTED_ORIGINS"] = csrf_trusted_origins

    def set_allowed_hosts(self):
        allowed_hosts = json.dumps([self.domain])

        click.secho(
            f"Automatically set PLAIN_ALLOWED_HOSTS={click.style(allowed_hosts, underline=True)}",
            bold=True,
        )

        # Set environment variables
        self.plain_env["PLAIN_ALLOWED_HOSTS"] = allowed_hosts
        self.custom_process_env["PLAIN_ALLOWED_HOSTS"] = allowed_hosts

    def run_preflight(self):
        if subprocess.run(["plain", "preflight"], env=self.plain_env).returncode:
            click.secho("Preflight check failed!", fg="red")
            sys.exit(1)

    def add_gunicorn(self):
        plain_db_installed = find_spec("plain.models") is not None

        # Watch .env files for reload
        extra_watch_files = []
        for f in os.listdir(APP_PATH.parent):
            if f.startswith(".env"):
                extra_watch_files.append(f)

        reload_extra = " ".join(f"--reload-extra-file {f}" for f in extra_watch_files)
        gunicorn_cmd = [
            "gunicorn",
            "--bind",
            f"{self.domain}:{self.port}",
            "--certfile",
            str(self.ssl_cert_path),
            "--keyfile",
            str(self.ssl_key_path),
            "--reload",
            "plain.wsgi:app",
            "--timeout",
            "60",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
            *reload_extra.split(),
            "--access-logformat",
            "'\"%(r)s\" status=%(s)s length=%(b)s dur=%(M)sms'",
        ]
        gunicorn = " ".join(gunicorn_cmd)

        if plain_db_installed:
            runserver_cmd = f"plain models db-wait && plain migrate && {gunicorn}"
        else:
            runserver_cmd = gunicorn

        if "WEB_CONCURRENCY" not in self.plain_env:
            # Default to two workers to prevent lockups
            self.plain_env["WEB_CONCURRENCY"] = "2"

        self.poncho.add_process("plain", runserver_cmd, env=self.plain_env)

    def add_entrypoints(self):
        for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
            self.poncho.add_process(
                f"plain dev entrypoint {entry_point.name}", env=self.plain_env
            )

    def add_pyproject_run(self):
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

    def add_services(self):
        services = Services.get_services(APP_PATH.parent)
        for name, data in services.items():
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "true",
                **data.get("env", {}),
            }
            self.poncho.add_process(name, data["cmd"], env=env)


cli.add_command(db_cli)
