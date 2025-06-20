import os

from plain.runtime import PLAIN_TEMP_PATH


class DevPid:
    """Manage a pidfile for the running ``plain dev`` command."""

    def __init__(self):
        self.pidfile = PLAIN_TEMP_PATH / "dev" / "dev.pid"

    def write(self):
        pid = os.getpid()
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        with self.pidfile.open("w+") as f:
            f.write(str(pid))

    def rm(self):
        if self.pidfile.exists():
            self.pidfile.unlink()

    def exists(self):
        if not self.pidfile.exists():
            return False
        try:
            pid = int(self.pidfile.read_text())
        except (ValueError, OSError):
            self.rm()
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            # Stale pidfile
            self.rm()
            return False
        return True
