import json
import os
import subprocess
import sys

import click
from dotenv import load_dotenv
from dotenv import set_key as dotenv_set_key
from honcho.manager import Manager as HonchoManager

from .utils import boltpackage_installed, get_repo_root


@click.command()
def cli():
    """Start local development"""
    # TODO check docker is available first
    repo_root = get_repo_root()
    app_dir = os.path.join(repo_root, "app")
    dot_bolt_dir = os.path.join(repo_root, ".bolt")

    django_env = {
        **os.environ,  # Make a copy before load_dotenv, since Django will do it's own version of that
        "PYTHONPATH": app_dir,
        "PYTHONUNBUFFERED": "true",
    }

    dotenv_path = os.path.join(repo_root, ".env")
    load_dotenv(dotenv_path)

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

    runserver_port = os.environ.get("PORT", "8000")

    if "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN" in os.environ:
        codespace_base_url = f"https://{os.environ['CODESPACE_NAME']}-{runserver_port}.{os.environ['GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN']}"
        click.secho(
            f"Automatically using Codespace BASE_URL={click.style(codespace_base_url, underline=True)}",
            bold=True,
        )
        django_env["BASE_URL"] = codespace_base_url

    if subprocess.run(["bolt", "django", "check"], env=django_env).returncode:
        click.secho("Django check failed!", fg="red")
        sys.exit(1)

    manager = HonchoManager()

    # Meant to work with Bolt Pro, but doesn't necessarily have to
    if "STRIPE_WEBHOOK_PATH" in os.environ:
        manager.add_process(
            "stripe",
            f"stripe listen --forward-to localhost:{runserver_port}{os.environ['STRIPE_WEBHOOK_PATH']}",
        )

    runserver_cmd = f"bolt django migrate && gunicorn --reload bolt.wsgi.default:application --access-logfile - --error-logfile - --reload-extra-file {dotenv_path} --access-logformat '\"%(r)s\" status=%(s)s length=%(b)s dur=%(M)sms'"

    # if boltpackage_installed("db"):
    manager.add_process("postgres", "bolt db start --logs")
    runserver_cmd = "bolt db wait && " + runserver_cmd

    manager.add_process("bolt", runserver_cmd, env=django_env)

    if "REDIS_URL" in os.environ:
        redis_url = os.environ["REDIS_URL"]
        if "localhost" in redis_url or "127.0.0.1" in redis_url:
            redis_name = os.path.basename(repo_root) + "-redis"
            redis_version = os.environ.get("REDIS_VERSION", "7")
            redis_port = redis_url.split(":")[-1]  # Assume no db index or anything
            manager.add_process(
                "redis",
                f"docker run --name {redis_name} --rm -p {redis_port}:6379 -v {dot_bolt_dir}/redis:/data redis:{redis_version} redis-server --save 60 1 --loglevel warning",
            )

    if "CELERY_APP" in os.environ:
        manager.add_process(
            "celery",
            f"hupper -w .env -m celery --app {os.environ['CELERY_APP']} worker --loglevel info",
            env=django_env,
        )

    if boltpackage_installed("tailwind"):
        manager.add_process("tailwind", "bolt-tailwind compile --watch")

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
