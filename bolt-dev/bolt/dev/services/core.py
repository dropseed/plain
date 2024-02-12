import os
import subprocess
from pathlib import Path

from bolt.runtime import APP_PATH, settings


class Services:
    def __init__(self):
        self.compose_project = APP_PATH.parent.name

        if Path("dev_services.yml").exists():
            self.compose_file = Path("dev_services.yml")
        else:
            self.compose_file = Path(__file__).parent / "compose.yml"

    def are_running(self):
        output = subprocess.check_output(
            [
                "docker-compose",
                "ls",
                "--filter",
                "name=" + self.compose_project,
            ],
        ).decode()
        return "running" in output

    def start(self, in_background=False):
        profiles = []
        env = {
            **os.environ,
            # Pass this through to compose.yml
            "BOLT_TEMP_PATH": settings.BOLT_TEMP_PATH,
        }

        if os.environ.get("REDIS_URL"):
            profiles.append("--profile")
            profiles.append("redis")

        if "localhost" in os.environ.get(
            "DATABASE_URL", ""
        ) or "127.0.0.1" in os.environ.get("DATABASE_URL", ""):
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
            return []

        compose_cmd = [
            "docker-compose",
            *profiles,
            "--project-name",
            self.compose_project,
            "-f",
            str(self.compose_file),
            "up",
        ]

        if in_background:
            compose_cmd.append("-d")

        subprocess.check_call(
            compose_cmd,
            env=env,
        )

        return profiles

    def shutdown(self):
        subprocess.check_call(["docker-compose", "down"])

    # Make this available as a context manager
    # ex. with Services() as services:
    def __enter__(self):
        if self.are_running():
            # Only want to do shutdown if the context manager didn't start it
            self._was_running = True
        else:
            self.start(in_background=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if not getattr(self, "_was_running", False):
            self.shutdown()
