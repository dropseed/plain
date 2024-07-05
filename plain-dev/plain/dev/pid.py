import os

from plain.runtime import settings


class Pid:
    def __init__(self):
        self.pidfile = settings.PLAIN_TEMP_PATH / "dev.pid"

    def write(self):
        pid = os.getpid()
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        with self.pidfile.open("w+") as f:
            f.write(str(pid))

    def rm(self):
        self.pidfile.unlink()

    def exists(self):
        return self.pidfile.exists()
