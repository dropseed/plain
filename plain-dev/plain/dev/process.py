import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .poncho.manager import Manager as PonchoManager
from .poncho.printer import Printer
from .state import checkout_state_path, find_project_root


def _pid_is_alive(pid: int) -> bool:
    """Return True if a process with *pid* currently exists."""
    try:
        os.kill(pid, 0)  # Signal 0 checks for existence – it does not kill.
    except OSError:
        return False
    return True


class Supervisor:
    """A single-instance, long-running dev process group.

    Only one supervisor may run per project. That's enforced by holding an
    exclusive advisory lock (``flock``) on the pidfile for the *entire* life of
    the process: a second supervisor simply fails to take the lock and bows out,
    and the kernel releases the lock when the holding process exits — so a crash
    can't leave a stale lock behind. The pid is written into the file too, but
    only so other commands can identify and signal the running supervisor — it
    is not what guards against duplicates.
    """

    # Filename this supervisor records its pid under, e.g. "dev.pid".
    state_filename: str
    log_dir: Path
    # Foreground command that re-runs this supervisor, e.g. ["dev", "services"].
    background_command: list[str]
    # Human label for "already running" warnings, e.g. "Services".
    display_name: str

    @classmethod
    def pidfile_path(cls) -> Path:
        """Where this checkout records which process owns the supervisor slot.

        Kept beside the checkout's other facts rather than in its `.plain`, so
        two worktrees that end up sharing one can't each report the other's
        server as already running — see `plain.dev.state`.

        Derived on use rather than at import, because it depends on the working
        directory: as a class attribute it would freeze before the process has
        finished deciding where it is, while reading like a constant.
        """
        return checkout_state_path(find_project_root(Path.cwd())) / cls.state_filename

    def __init__(self):
        self.pid = os.getpid()
        self._lock_fd: int | None = None
        self.log_path: Path | None = None
        self.printer: Printer | None = None
        self.poncho: PonchoManager | None = None

    # ------------------------------------------------------------------
    # Reads (pure, lock-free – cheap enough for the per-command hot path)
    # ------------------------------------------------------------------
    @classmethod
    def read_pidfile(cls) -> int | None:
        """Return the PID recorded in the pidfile (or ``None``)."""
        try:
            return int(cls.pidfile_path().read_text())
        except (ValueError, OSError):
            # Missing, empty (released), or partial – treat as absent.
            return None

    @classmethod
    def running_pid(cls) -> int | None:
        """Return a *running* supervisor PID, or ``None`` if none is alive."""
        pid = cls.read_pidfile()
        if pid is None or not _pid_is_alive(pid):
            return None
        return pid

    @classmethod
    def already_running_message(cls, pid: int | None) -> str:
        """The single source of truth for the 'slot is taken' warning."""
        return f"{cls.display_name} already running (pid={pid})"

    # ------------------------------------------------------------------
    # Single-instance ownership (the lock is held for our whole lifetime)
    # ------------------------------------------------------------------
    def acquire(self) -> bool:
        """Claim sole ownership for this process's lifetime.

        Returns ``True`` if we now hold it, ``False`` if another live supervisor
        already does (in which case the caller must not start – a second one
        would collide on shared services like the database). A pidfile left by a
        dead supervisor is reclaimed automatically: its lock is already gone.
        """
        pidfile = self.pidfile_path()
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(pidfile, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False

        os.ftruncate(fd, 0)
        os.write(fd, str(self.pid).encode())
        self._lock_fd = fd  # Held (open) until release() / process exit.
        return True

    def release(self) -> None:
        """Release ownership: clear the recorded pid and drop the lock."""
        if self._lock_fd is None:
            return
        os.ftruncate(self._lock_fd, 0)
        os.close(self._lock_fd)  # Closing the fd releases the flock.
        self._lock_fd = None

    @classmethod
    def spawn_background(cls, *extra_args: str) -> int:
        """Start this supervisor detached in the background; return its pid."""
        proc = subprocess.Popen(
            [sys.executable, "-m", "plain", *cls.background_command, *extra_args],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc.pid

    @classmethod
    def _has_live_owner(cls) -> bool:
        """True if a live supervisor currently holds the lock.

        A read-only probe: it does not write to or truncate the pidfile, so it
        can't be misread by a concurrent command (unlike claiming the lock).
        """
        try:
            fd = os.open(cls.pidfile_path(), os.O_RDONLY)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True  # Someone live holds it.
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)

    def stop_process(self) -> None:
        """Terminate the running supervisor, if one actually holds the lock."""
        pid = self.read_pidfile()
        if pid is None:
            return

        # If nobody holds the lock, no supervisor is alive — the recorded pid is
        # stale (and could even be a reused, unrelated pid), so don't signal it.
        if not self._has_live_owner():
            return

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return  # Already gone.

        deadline = time.time() + 10
        while time.time() < deadline:
            if not _pid_is_alive(pid):
                return  # Exited gracefully; it cleared its own pidfile.
            time.sleep(0.1)

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Logging / Poncho helpers
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

    def init_poncho(self, print_func: Any) -> PonchoManager:  # noqa: D401
        """Return a :class:`~plain.dev.poncho.manager.Manager` instance."""
        if self.log_path is None:
            self.prepare_log()

        self.printer = Printer(print_func, log_file=self.log_path)
        self.poncho = PonchoManager(printer=self.printer)
        return self.poncho

    def close(self) -> None:
        if self.printer:
            self.printer.close()
