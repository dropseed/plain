import os
import subprocess
from pathlib import Path

import click

from bolt.runtime import APP_PATH, settings


@click.group("services")
def cli():
    """Run databases and additional dev services in Docker Compose"""
    pass


@cli.command()
def up():
    """Start services"""
    click.secho("Starting services...", bold=True)

    compose_project = APP_PATH.parent.name

    compose_file = Path(__file__).parent / "compose.yml"

    custom_compose_file = Path("dev_services.yml")
    if custom_compose_file.exists():
        compose_file = custom_compose_file

    profiles = []
    env = {
        **os.environ,
        "BOLT_TEMP_PATH": settings.BOLT_TEMP_PATH,
    }

    if os.environ.get("REDIS_URL"):
        profiles.append("--profile")
        profiles.append("redis")

    if os.environ.get("DATABASE_URL"):
        profiles.append("--profile")
        profiles.append("postgres")

        from bolt.db import database_url

        parsed_db_url = database_url.parse(os.environ.get("DATABASE_URL"))
        if parsed_db_url["ENGINE"] != "bolt.db.backends.postgresql":
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")

        env["POSTGRES_DB"] = parsed_db_url.get("NAME", "postgres")
        env["POSTGRES_USER"] = parsed_db_url.get("USER", "postgres")
        env["POSTGRES_PASSWORD"] = parsed_db_url.get("PASSWORD", "postgres")
        env["POSTGRES_PORT"] = str(parsed_db_url.get("PORT", "5432"))

    if not profiles:
        click.secho("No services to start", fg="yellow")
        return

    subprocess.check_call(
        [
            "docker-compose",
            *profiles,
            "--project-name",
            compose_project,
            "-f",
            str(compose_file),
            "up",
        ],
        env=env,
    )


@cli.command()
def down():
    subprocess.check_call(["docker-compose", "down"])
