import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import click
from dotenv import load_dotenv
from honcho.manager import Manager as HonchoManager

from bolt.runtime import settings

from ..utils import boltpackage_installed, has_pyproject_toml


@click.command()
def cli():
    """Start local development"""
    # TODO check docker is available first
    project_root = settings.APP_PATH.parent

    bolt_env = {
        **os.environ,  # Make a copy before load_dotenv, since Bolt will do it's own version of that
        "PYTHONUNBUFFERED": "true",
    }

    dotenv_path = os.path.join(project_root, ".env")
    load_dotenv(dotenv_path)

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
        bolt_db_installed = True
    except ImportError:
        bolt_db_installed = False

    manager = HonchoManager()

    gunicorn = f"gunicorn --reload bolt.wsgi:app --timeout 0 --workers 2 --access-logfile - --error-logfile - --reload-extra-file {dotenv_path} --access-logformat '\"%(r)s\" status=%(s)s length=%(b)s dur=%(M)sms'"

    if bolt_db_installed:
        runserver_cmd = f"bolt dev db wait && bolt legacy migrate && {gunicorn}"
        manager.add_process("postgres", "bolt dev db start --logs")
    else:
        runserver_cmd = gunicorn

    manager.add_process("bolt", runserver_cmd, env=bolt_env)

    if "REDIS_URL" in os.environ:
        redis_url = os.environ["REDIS_URL"]
        if "localhost" in redis_url or "127.0.0.1" in redis_url:
            redis_name = os.path.basename(project_root) + "-redis"
            redis_version = os.environ.get("REDIS_VERSION", "7")
            redis_port = redis_url.split(":")[-1]  # Assume no db index or anything
            manager.add_process(
                "redis",
                f"docker run --name {redis_name} --rm -p {redis_port}:6379 -v {settings.BOLT_TEMP_PATH}/redis:/data redis:{redis_version} redis-server --save 60 1 --loglevel warning",
            )

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
