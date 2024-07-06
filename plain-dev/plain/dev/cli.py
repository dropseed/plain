import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import click
from honcho.manager import Manager as HonchoManager

from plain.runtime import APP_PATH

from .db import cli as db_cli
from .pid import Pid
from .services import Services
from .utils import has_pyproject_toml, plainpackage_installed

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@click.group(invoke_without_command=True)
@click.pass_context
@click.option(
    "--port",
    "-p",
    default=8000,
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


class Dev:
    def __init__(self, *, port):
        self.manager = HonchoManager()
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

    def run(self):
        pid = Pid()
        pid.write()

        try:
            self.add_csrf_trusted_origins()
            self.run_preflight()
            self.add_gunicorn()
            self.add_tailwind()
            self.add_pyproject_run()
            self.add_services()

            self.manager.loop()

            return self.manager.returncode
        finally:
            pid.rm()

    def add_csrf_trusted_origins(self):
        if "PLAIN_CSRF_TRUSTED_ORIGINS" in os.environ:
            return

        csrf_trusted_origins = json.dumps(
            [f"http://localhost:{self.port}", f"http://127.0.0.1:{self.port}"]
        )

        click.secho(
            f"Automatically set PLAIN_CSRF_TRUSTED_ORIGINS={click.style(csrf_trusted_origins, underline=True)}",
            bold=True,
        )

        # Set BASE_URL for plain and custom processes
        self.plain_env["PLAIN_CSRF_TRUSTED_ORIGINS"] = csrf_trusted_origins
        self.custom_process_env["PLAIN_CSRF_TRUSTED_ORIGINS"] = csrf_trusted_origins

    def run_preflight(self):
        if subprocess.run(["plain", "preflight"], env=self.plain_env).returncode:
            click.secho("Preflight check failed!", fg="red")
            sys.exit(1)

    def add_gunicorn(self):
        plain_db_installed = find_spec("plain.models") is not None

        # TODO not necessarily watching the right .env...
        # could return path from env.load?
        extra_watch_files = []
        for f in os.listdir(APP_PATH.parent):
            if f.startswith(".env"):
                # Will include some extra, but good enough for now
                extra_watch_files.append(f)

        reload_extra = " ".join(f"--reload-extra-file {f}" for f in extra_watch_files)
        gunicorn = f"gunicorn --bind 127.0.0.1:{self.port} --reload plain.wsgi:app --timeout 60 --access-logfile - --error-logfile - {reload_extra} --access-logformat '\"%(r)s\" status=%(s)s length=%(b)s dur=%(M)sms'"

        if plain_db_installed:
            runserver_cmd = (
                f"plain models db-wait && plain legacy migrate && {gunicorn}"
            )
        else:
            runserver_cmd = gunicorn

        if "WEB_CONCURRENCY" not in self.plain_env:
            # Default to two workers so request log etc are less
            # likely to get locked up
            self.plain_env["WEB_CONCURRENCY"] = "2"

        self.manager.add_process("plain", runserver_cmd, env=self.plain_env)

    def add_tailwind(self):
        if not plainpackage_installed("tailwind"):
            return

        self.manager.add_process("tailwind", "plain tailwind compile --watch")

    def add_pyproject_run(self):
        if not has_pyproject_toml(APP_PATH.parent):
            return

        with open(Path(APP_PATH.parent, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)

        for name, data in (
            pyproject.get("tool", {}).get("plain", {}).get("dev", {}).get("run", {})
        ).items():
            env = {
                **self.custom_process_env,
                **data.get("env", {}),
            }
            self.manager.add_process(name, data["cmd"], env=env)

    def add_services(self):
        services = Services.get_services(APP_PATH.parent)
        for name, data in services.items():
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "true",
                **data.get("env", {}),
            }
            self.manager.add_process(name, data["cmd"], env=env)


cli.add_command(db_cli)
