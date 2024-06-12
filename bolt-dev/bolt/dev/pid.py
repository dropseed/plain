import os

from bolt.runtime import settings


class Pid:
    def __init__(self):
        self.pidfile = settings.BOLT_TEMP_PATH / "dev.pid"

    def write(self):
        pid = os.getpid()
        with self.pidfile.open("w+") as f:
            f.write(str(pid))

    def rm(self):
        self.pidfile.unlink()

    def exists(self):
        return self.pidfile.exists()
