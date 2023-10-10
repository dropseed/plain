import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import click
from honcho.manager import Manager as HonchoManager

from bolt.runtime import settings

from ..utils import boltpackage_installed, has_pyproject_toml


@click.command()
def cli():
    """Start local development"""
    # TODO check docker is available first
    project_root = settings.APP_PATH.parent

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

    if subprocess.run(["bolt", "legacy", "check"], env=bolt_env).returncode:
        click.secho("Bolt check failed!", fg="red")
        sys.exit(1)

    # if subprocess.run(["bolt", "env", "check"], env=bolt_env).returncode:
    #     click.secho("Bolt env check failed!", fg="red")
    #     sys.exit(1)

    try:
        from bolt import db

        bolt_db_installed = True
    except ImportError:
        bolt_db_installed = False

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
        runserver_cmd = f"bolt dev db wait && bolt legacy migrate && {gunicorn}"
        manager.add_process("postgres", "bolt dev db start --logs")
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
            pyproject.get("tool", {}).get("bolt", {}).get("work", {}).get("run", {})
        ).items():
            env = {
                **custom_env,
                **data.get("env", {}),
            }
            manager.add_process(name, data["cmd"], env=env)

    manager.loop()

    sys.exit(manager.returncode)
