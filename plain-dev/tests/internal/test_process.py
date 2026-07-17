"""Single-instance ownership for the dev supervisors.

Ownership is enforced by an advisory ``flock`` held for the process's lifetime,
so a second supervisor can never start (and thus can never orphan the first's
marker — the bug this replaced), and a dead supervisor's marker is reclaimed
automatically because the kernel has already dropped its lock.
"""

import os
import tempfile
from pathlib import Path

from plain.dev.process import Supervisor


def make_supervisor(tmp_path: Path):
    class _Supervisor(Supervisor):
        pidfile = tmp_path / "dev" / "thing.pid"
        log_dir = tmp_path / "dev" / "logs"

    return _Supervisor()


def test_acquire_records_our_pid():
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        try:
            assert s.acquire() is True
            assert s.read_pidfile() == s.pid
            assert s.running_pid() == s.pid
        finally:
            s.release()


def test_second_acquire_is_blocked_while_held():
    """A second supervisor can't claim ownership while one holds the lock."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        first = make_supervisor(tmp_path)
        second = make_supervisor(tmp_path)
        try:
            assert first.acquire() is True
            # flock conflicts even within one process (separate open file
            # descriptions), which is exactly the single-instance guarantee.
            assert second.acquire() is False
            assert second.read_pidfile() == first.pid  # untouched
        finally:
            first.release()


def test_release_frees_the_lock():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        first = make_supervisor(tmp_path)
        assert first.acquire() is True
        first.release()

        second = make_supervisor(tmp_path)
        try:
            assert second.acquire() is True
        finally:
            second.release()


def test_release_clears_recorded_pid():
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        assert s.acquire() is True
        s.release()
        assert s.read_pidfile() is None
        assert s.running_pid() is None


def test_acquire_reclaims_a_dead_supervisors_marker():
    """A pidfile left by a crashed supervisor (lock already gone) is reclaimed."""
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        s.pidfile.parent.mkdir(parents=True, exist_ok=True)
        s.pidfile.write_text(str(_dead_pid()))  # stale marker, no lock held

        try:
            assert s.acquire() is True
            assert s.read_pidfile() == s.pid
        finally:
            s.release()


def test_running_pid_is_none_for_dead_process():
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        s.pidfile.parent.mkdir(parents=True, exist_ok=True)
        s.pidfile.write_text(str(_dead_pid()))
        assert s.running_pid() is None


def test_corrupted_pidfile_reads_as_absent():
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        s.pidfile.parent.mkdir(parents=True, exist_ok=True)
        s.pidfile.write_text("not-a-pid")
        assert s.read_pidfile() is None
        assert s.running_pid() is None
        try:
            assert s.acquire() is True  # a fresh claim overwrites the garbage
            assert s.read_pidfile() == s.pid
        finally:
            s.release()


def test_stop_process_ignores_a_stale_marker():
    """A stale pid (its supervisor is gone) must not be signalled — that pid
    could have been recycled by an unrelated process."""
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        s.pidfile.parent.mkdir(parents=True, exist_ok=True)
        dead = _dead_pid()
        s.pidfile.write_text(str(dead))

        s.stop_process()  # No live owner holds the lock → no signal sent.
        # The marker is left untouched; it self-heals on the next acquire().
        assert s.read_pidfile() == dead


def test_stop_process_is_a_noop_without_a_marker():
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        s.stop_process()  # Nothing recorded → nothing to do.
        assert s.read_pidfile() is None


def test_has_live_owner_tracks_the_lock():
    with tempfile.TemporaryDirectory() as tmp:
        s = make_supervisor(Path(tmp))
        assert s._has_live_owner() is False  # No pidfile yet.
        assert s.acquire() is True
        assert s._has_live_owner() is True  # We hold the lock.
        s.release()
        assert s._has_live_owner() is False  # Released.


def _dead_pid() -> int:
    """A pid that is (almost certainly) not running."""
    pid = 999_999
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return pid
        pid -= 1
