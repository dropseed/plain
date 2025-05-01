import os
import subprocess
import time
import tomllib
from importlib.util import find_spec
from pathlib import Path

import click

from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .poncho.manager import Manager as PonchoManager
from .utils import has_pyproject_toml


class ServicesPid:
    def __init__(self):
        self.pidfile = PLAIN_TEMP_PATH / "dev" / "services.pid"

    def write(self):
        pid = os.getpid()
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        with self.pidfile.open("w+") as f:
            f.write(str(pid))

    def rm(self):
        self.pidfile.unlink()

    def exists(self):
        return self.pidfile.exists()


class Services:
    @staticmethod
    def get_services(root):
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

    def __init__(self):
        self.poncho = PonchoManager()

    @staticmethod
    def are_running():
        pid = ServicesPid()
        return pid.exists()

    def run(self):
        # Each user of Services will have to check if it is running by:
        # - using the context manager (with Services())
        # - calling are_running() directly
        pid = ServicesPid()
        pid.write()

        try:
            services = self.get_services(APP_PATH.parent)
            for name, data in services.items():
                env = {
                    **os.environ,
                    "PYTHONUNBUFFERED": "true",
                    **data.get("env", {}),
                }
                self.poncho.add_process(name, data["cmd"], env=env)

            self.poncho.loop()
        finally:
            pid.rm()

    def __enter__(self):
        if not self.get_services(APP_PATH.parent):
            # No-op if no services are defined
            return

        if self.are_running():
            click.secho("Services already running", fg="yellow")
            return

        print("Starting `plain dev services`")
        self._subprocess = subprocess.Popen(
            ["plain", "dev", "services"], cwd=APP_PATH.parent
        )

        if find_spec("plain.models"):
            time.sleep(0.5)  # Give it a chance to hit on the first try
            subprocess.check_call(["plain", "models", "db-wait"], env=os.environ)
        else:
            # A bit of a hack to wait for the services to start
            time.sleep(3)

    def __exit__(self, *args):
        if not hasattr(self, "_subprocess"):
            return

        self._subprocess.terminate()

        # Flush the buffer so the output doesn't spill over
        self._subprocess.communicate()
