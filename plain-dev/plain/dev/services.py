import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import click

from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .process import Supervisor
from .utils import has_pyproject_toml


def auto_start_services() -> None:
    """Start dev *services* in the background if not already running."""

    # Check if we're in CI and auto-start is not explicitly enabled
    if os.environ.get("CI") and os.environ.get("DEV_SERVICES_AUTO") is None:
        return

    if os.environ.get("DEV_SERVICES_AUTO", "true") not in [
        "1",
        "true",
        "yes",
    ]:
        return

    # Only auto-start services for commands that need the database/runtime
    service_commands = {
        "postgres",
        "dev",
        "migrations",
        "preflight",
        "request",
        "run",
        "shell",
        "test",
    }
    if not (service_commands & set(sys.argv)):
        return

    # Don't do anything if it looks like a "services" command is being run explicitly
    if "dev" in sys.argv:
        if "logs" in sys.argv or "services" in sys.argv or "--stop" in sys.argv:
            return

    if not ServicesSupervisor.get_services(APP_PATH.parent):
        return

    # Cheap pre-check to avoid a needless spawn; the spawned supervisor's
    # acquire() is the real guarantee against double-starting.
    if ServicesSupervisor.running_pid():
        return

    click.secho(
        "Starting background dev services (terminate with `plain dev --stop`)...",
        dim=True,
    )

    ServicesSupervisor.spawn_background()

    # Give services time to start and retry the check
    wait_times = [0.5, 1, 1]  # First check at 0.5s, then 1s intervals
    for wait_time in wait_times:
        time.sleep(wait_time)
        if ServicesSupervisor.running_pid():
            return  # Services started successfully

    # Only show error after multiple attempts
    if not ServicesSupervisor.running_pid():
        click.secho(
            "Failed to start dev services. Here are the logs:",
            fg="red",
        )
        subprocess.run(
            ["plain", "dev", "logs", "--services"],
            check=False,
        )
        sys.exit(1)


class ServicesSupervisor(Supervisor):
    state_filename = "services.pid"
    log_dir = PLAIN_TEMP_PATH / "dev" / "logs" / "services"
    background_command = ["dev", "services"]
    display_name = "Services"

    @staticmethod
    def get_services(root: str | Path) -> dict[str, Any]:
        if not has_pyproject_toml(root):
            return {}

        with open(Path(root, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)

        return (
            pyproject.get("tool", {})
            .get("plain", {})
            .get("dev", {})
            .get("services", {})
        )

    def run(self) -> None:
        if not self.acquire():
            click.secho(self.already_running_message(self.read_pidfile()), fg="yellow")
            return

        self.prepare_log()
        self.init_poncho(print)

        assert self.poncho is not None, "poncho should be initialized"

        try:
            services = self.get_services(APP_PATH.parent)
            for name, data in services.items():
                env = {
                    **os.environ,
                    "PYTHONUNBUFFERED": "true",
                    "FORCE_COLOR": "1",
                    **data.get("env", {}),
                }
                self.poncho.add_process(name, data["cmd"], env=env)

            self.poncho.loop()
        finally:
            self.release()
            self.close()
