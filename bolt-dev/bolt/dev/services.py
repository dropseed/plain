import os
from pathlib import Path

import click
from honcho.manager import Manager as HonchoManager

from bolt.runtime import APP_PATH

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
            pyproject.get("tool", {}).get("bolt", {}).get("dev", {}).get("services", {})
        )

    def __init__(self):
        self.manager = HonchoManager()

    def __enter__(self):
        if Pid().exists():
            click.secho("Services already running in `bolt dev` command", fg="yellow")
            return

        services = self.get_services(APP_PATH.parent)
        for name, data in services.items():
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "true",
                **data.get("env", {}),
            }
            self.manager.add_process(name, data["cmd"], env=env)

        self.manager.loop()

    def __exit__(self, *args):
        self.manager.terminate()
