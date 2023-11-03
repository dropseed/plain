import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import click
from honcho.manager import Manager as HonchoManager

from bolt.runtime import APP_PATH

from .db import cli as db_cli
from .services import cli as services_cli
from .utils import boltpackage_installed, has_pyproject_toml

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Start local development"""

    if ctx.invoked_subcommand:
        return

    # TODO check docker is available first
    project_root = APP_PATH.parent

    bolt_env = {
        **os.environ,
        "PYTHONUNBUFFERED": "true",
    }

    runserver_port = os.environ.get("PORT", "8000")

    if "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN" in os.environ:
        codespace_base_url = f"https://{os.environ['CODESPACE_NAME']}-{runserver_port}.{os.environ['GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN']}"
        click.secho(
            f"Automatically using Codespace BASE_URL={click.style(codespace_base_url, underline=True)}",
            bold=True,
        )
        bolt_env["BASE_URL"] = codespace_base_url

    if subprocess.run(["bolt", "preflight"], env=bolt_env).returncode:
        click.secho("Preflight check failed!", fg="red")
        sys.exit(1)

    # if subprocess.run(["bolt", "env", "check"], env=bolt_env).returncode:
    #     click.secho("Bolt env check failed!", fg="red")
    #     sys.exit(1)

    bolt_db_installed = find_spec("bolt.db") is not None

    manager = HonchoManager()

    # TODO not necessarily watching the right .env...
    # could return path from env.load?
    extra_watch_files = []
    for f in os.listdir(project_root):
        if f.startswith(".env"):
            # Will include some extra, but good enough for now
            extra_watch_files.append(f)

    reload_extra = " ".join(f"--reload-extra-file {f}" for f in extra_watch_files)
    gunicorn = f"gunicorn --reload bolt.wsgi:app --timeout 0 --workers 2 --access-logfile - --error-logfile - {reload_extra} --access-logformat '\"%(r)s\" status=%(s)s length=%(b)s dur=%(M)sms'"

    if bolt_db_installed:
        runserver_cmd = f"bolt db wait && bolt legacy migrate && {gunicorn}"
        manager.add_process("dev", "bolt dev services up")
    else:
        runserver_cmd = gunicorn

    manager.add_process("bolt", runserver_cmd, env=bolt_env)

    if boltpackage_installed("tailwind"):
        manager.add_process("tailwind", "bolt tailwind compile --watch")

    custom_env = {
        **bolt_env,
        "PORT": runserver_port,
        "PYTHONPATH": os.path.join(project_root, "app"),
    }

    if project_root and has_pyproject_toml(project_root):
        with open(Path(project_root, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)
        for name, data in (
            pyproject.get("tool", {}).get("bolt", {}).get("dev", {}).get("run", {})
        ).items():
            env = {
                **custom_env,
                **data.get("env", {}),
            }
            manager.add_process(name, data["cmd"], env=env)

    package_json = Path("package.json")
    if package_json.exists():
        with package_json.open() as f:
            package = json.load(f)

        if package.get("scripts", {}).get("dev"):
            manager.add_process("npm", "npm run dev", env=custom_env)

    manager.loop()

    sys.exit(manager.returncode)


cli.add_command(db_cli)
cli.add_command(services_cli)
