import os
import subprocess
import time
from importlib.util import find_spec
from pathlib import Path

import click
from honcho.manager import Manager as HonchoManager

from plain.runtime import APP_PATH

from .pid import Pid
from .utils import has_pyproject_toml

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


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
        self.manager = HonchoManager()

    def run(self):
        services = self.get_services(APP_PATH.parent)
        for name, data in services.items():
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "true",
                **data.get("env", {}),
            }
            self.manager.add_process(name, data["cmd"], env=env)

        self.manager.loop()

    def __enter__(self):
        if not self.get_services(APP_PATH.parent):
            # No-op if no services are defined
            return

        if Pid().exists():
            click.secho("Services already running in `plain dev` command", fg="yellow")
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
