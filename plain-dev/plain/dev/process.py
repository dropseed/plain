import os
import time
from pathlib import Path

from .poncho.manager import Manager as PonchoManager
from .poncho.printer import Printer


class ProcessManager:
    pidfile: Path
    log_dir: Path

    def __init__(self):
        self.pid = os.getpid()
        self.log_path: Path | None = None
        self.printer: Printer | None = None
        self.poncho: PonchoManager | None = None

    # ------------------------------------------------------------------
    # Class-level pidfile helpers (usable without instantiation)
    # ------------------------------------------------------------------
    @classmethod
    def read_pidfile(cls) -> int | None:
        """Return the PID recorded in *cls.pidfile* (or ``None``)."""
        if not cls.pidfile.exists():
            return None

        try:
            return int(cls.pidfile.read_text())
        except (ValueError, OSError):
            # Corrupted pidfile – remove it so we don't keep trying.
            cls.rm_pidfile()
            return None

    @classmethod
    def rm_pidfile(cls) -> None:
        if cls.pidfile and cls.pidfile.exists():
            cls.pidfile.unlink(missing_ok=True)  # Python 3.8+

    @classmethod
    def running_pid(cls) -> int | None:
        """Return a *running* PID or ``None`` if the process is not alive."""
        pid = cls.read_pidfile()
        if pid is None:
            return None

        try:
            os.kill(pid, 0)  # Does not kill – merely checks for existence.
        except OSError:
            cls.rm_pidfile()
            return None

        return pid

    def write_pidfile(self) -> None:
        """Create/overwrite the pidfile for *this* process."""
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        with self.pidfile.open("w+", encoding="utf-8") as f:
            f.write(str(self.pid))

    def stop_process(self) -> None:
        """Terminate the process recorded in the pidfile, if it is running."""
        pid = self.read_pidfile()
        if pid is None:
            return

        # Try graceful termination first (SIGTERM)…
        try:
            os.kill(pid, 15)
        except OSError:
            # Process already gone – ensure we clean up.
            self.rm_pidfile()
            self.close()
            return

        timeout = 10  # seconds
        start = time.time()
        while time.time() - start < timeout:
            try:
                os.kill(pid, 0)
            except OSError:
                break  # Process has exited.
            time.sleep(0.1)

        else:  # Still running – force kill.
            try:
                os.kill(pid, 9)
            except OSError:
                pass

        self.rm_pidfile()
        self.close()

    # ------------------------------------------------------------------
    # Logging / Poncho helpers (unchanged)
    # ------------------------------------------------------------------
    def prepare_log(self) -> Path:
        """Create the log directory and return a path for *this* run."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Keep the 5 most recent log files.
        logs = sorted(
            self.log_dir.glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in logs[5:]:
            old.unlink(missing_ok=True)

        self.log_path = self.log_dir / f"{self.pid}.log"
        return self.log_path

    def init_poncho(self, print_func) -> PonchoManager:  # noqa: D401
        """Return a :class:`~plain.dev.poncho.manager.Manager` instance."""
        if self.log_path is None:
            self.prepare_log()

        self.printer = Printer(print_func, log_file=self.log_path)
        self.poncho = PonchoManager(printer=self.printer)
        return self.poncho

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self.printer:
            self.printer.close()
