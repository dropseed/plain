import json
import os
import subprocess
import sys

import click
from dotenv import set_key as dotenv_set_key
from forgecore import Forge
from honcho.manager import Manager as HonchoManager


@click.command("work")
def cli():
    """Start local development"""
    # TODO check docker is available first

    forge = Forge()

    repo_root = forge.repo_root
    if not repo_root:
        click.secho("Not in a git repository", fg="red")
        sys.exit(1)

    dotenv_path = os.path.join(repo_root, ".env")

    django_env = {
        "PYTHONPATH": forge.project_dir,
        "PYTHONUNBUFFERED": "true",
    }
    if (
        "STRIPE_WEBHOOK_PATH" in os.environ
        and "STRIPE_WEBHOOK_SECRET" not in os.environ
    ):
        # TODO check stripe command available, need to do the same with docker
        stripe_webhook_secret = (
            subprocess.check_output(["stripe", "listen", "--print-secret"])
            .decode()
            .strip()
        )
        click.secho("Adding automatic STRIPE_WEBHOOK_SECRET to .env", fg="green")
        dotenv_set_key(
            dotenv_path,
            "STRIPE_WEBHOOK_SECRET",
            stripe_webhook_secret,
            quote_mode="auto",
        )
        os.environ["STRIPE_WEBHOOK_SECRET"] = stripe_webhook_secret

    if forge.manage_cmd("check", env=django_env).returncode:
        click.secho("Django check failed!", fg="red")
        sys.exit(1)

    managepy = forge.user_or_forge_path("manage.py")

    runserver_port = os.environ.get("RUNSERVER_PORT", "8000")

    manage_cmd = f"python {managepy}"

    manager = HonchoManager()

    # Meant to work with Forge Pro, but doesn't necessarily have to
    if "STRIPE_WEBHOOK_PATH" in os.environ:
        manager.add_process(
            "stripe",
            f"stripe listen --forward-to localhost:{runserver_port}{os.environ['STRIPE_WEBHOOK_PATH']}",
        )

    # So this can work in development too...
    forge_executable = os.path.join(os.path.dirname(sys.executable), "forge")

    # TODO if forgedb installed
    manager.add_process("postgres", f"{forge_executable} db start --logs")

    manager.add_process(
        "django",
        f"{manage_cmd} dbwait && {manage_cmd} migrate && {manage_cmd} runserver {runserver_port}",
        env={
            **os.environ,
            **django_env,
        },
    )

    manager.add_process("tailwind", f"{forge_executable} tailwind compile --watch")

    if "NGROK_SUBDOMAIN" in os.environ:
        manager.add_process(
            "ngrok",
            f"ngrok http {runserver_port} --log stdout --subdomain {os.environ['NGROK_SUBDOMAIN']}",
        )

    # Run package.json "watch" script automatically
    package_json = os.path.join(repo_root, "package.json")
    if os.path.exists(package_json):
        with open(package_json) as f:
            package_json_data = json.load(f)
        if "watch" in package_json_data.get("scripts", {}):
            manager.add_process(
                "npm watch",
                "npm run watch",
            )

    manager.loop()

    sys.exit(manager.returncode)


if __name__ == "__main__":
    cli()
