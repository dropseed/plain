import os
import tomllib
from pathlib import Path

from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .process import ProcessManager
from .utils import has_pyproject_toml


class ServicesProcess(ProcessManager):
    pidfile = PLAIN_TEMP_PATH / "dev" / "services.pid"
    log_dir = PLAIN_TEMP_PATH / "dev" / "logs" / "services"

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

    def run(self):
        self.write_pidfile()
        self.prepare_log()
        self.init_poncho(print)

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
            self.rm_pidfile()
            self.close()
