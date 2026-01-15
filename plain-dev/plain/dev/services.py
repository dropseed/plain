import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import click

from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .process import ProcessManager
from .utils import has_pyproject_toml


def auto_start_services() -> None:
    """Start dev *services* in the background if not already running."""

    # Check if we're in CI and auto-start is not explicitly enabled
    if os.environ.get("CI") and os.environ.get("PLAIN_DEV_SERVICES_AUTO") is None:
        return

    if os.environ.get("PLAIN_DEV_SERVICES_AUTO", "true") not in [
        "1",
        "true",
        "yes",
    ]:
        return

    # Only auto-start services for commands that need the database/runtime
    service_commands = {
        "db",
        "makemigrations",
        "migrate",
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

    if not ServicesProcess.get_services(APP_PATH.parent):
        return

    if ServicesProcess.running_pid():
        return

    click.secho(
        "Starting background dev services (terminate with `plain dev --stop`)...",
        dim=True,
    )

    subprocess.Popen(
        [sys.executable, "-m", "plain", "dev", "services", "--start"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Give services time to start and retry the check
    wait_times = [0.5, 1, 1]  # First check at 0.5s, then 1s intervals
    for wait_time in wait_times:
        time.sleep(wait_time)
        if ServicesProcess.running_pid():
            return  # Services started successfully

    # Only show error after multiple attempts
    if not ServicesProcess.running_pid():
        click.secho(
            "Failed to start dev services. Here are the logs:",
            fg="red",
        )
        subprocess.run(
            ["plain", "dev", "logs", "--services"],
            check=False,
        )
        sys.exit(1)


class ServicesProcess(ProcessManager):
    pidfile = PLAIN_TEMP_PATH / "dev" / "services.pid"
    log_dir = PLAIN_TEMP_PATH / "dev" / "logs" / "services"

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
        self.write_pidfile()
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
            self.rm_pidfile()
            self.close()
