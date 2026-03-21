"""SIGUSR1-based memory leak detection for server workers.

Three-phase recording: signal 1 starts tracemalloc (snapshot A),
signal 2 takes midpoint (snapshot B), signal 3 stops and computes
the intersection of (B-A) and (C-B) — only allocations that grew
in BOTH halves are reported, filtering one-time init noise.
"""

from __future__ import annotations

import gc
import json
import os
import tempfile
import time
import tracemalloc

from plain.logs import get_framework_logger

log = get_framework_logger()

# Per-worker state machine: 0=idle, 1=phase 1, 2=phase 2
_phase: int = 0
_snapshot_a: tracemalloc.Snapshot | None = None
_snapshot_b: tracemalloc.Snapshot | None = None
_rss_start: int = 0
_started_at: float = 0.0


def profile_path(pid: int) -> str:
    """Path where a worker writes its memory profile."""
    return os.path.join(tempfile.gettempdir(), f"plain-memory-{pid}.json")


def _rss_bytes() -> int:
    from plain.utils.os import get_rss_bytes

    return get_rss_bytes()


def _is_noise(filename: str) -> bool:
    """Filter stdlib, tracemalloc, and self from results."""
    return (
        ("/lib/python" in filename and "site-packages" not in filename)
        or "<frozen" in filename
        or "tracemalloc" in filename
        or filename == __file__
    )


def _growers_by_lineno(stats: list) -> dict[tuple[str, int], int]:
    """Extract {(file, line): size_diff} from snapshot comparison stats."""
    result = {}
    for stat in stats:
        fn = stat.traceback[0].filename
        if _is_noise(fn):
            continue
        if stat.size_diff > 0:
            key = (fn, stat.traceback[0].lineno)
            result[key] = stat.size_diff
    return result


_MAX_DURATION = 300  # 5 minutes — auto-stop if recording is left running


def _reset() -> None:
    """Reset state to idle, stopping tracemalloc if running."""
    global _phase, _snapshot_a, _snapshot_b, _rss_start, _started_at
    if tracemalloc.is_tracing():
        tracemalloc.stop()
    _phase = 0
    _snapshot_a = None
    _snapshot_b = None
    _rss_start = 0
    _started_at = 0.0


def signal_handler() -> None:
    """Advance the recording state machine. Called from SIGUSR1 handler."""
    try:
        _advance()
    except Exception:
        log.exception(
            "Memory signal handler failed, resetting",
            extra={"pid": os.getpid()},
        )
        _reset()


def _advance() -> None:
    """State machine implementation. Separated so signal_handler can catch errors."""
    global _phase, _snapshot_a, _snapshot_b, _rss_start, _started_at

    pid = os.getpid()

    # Safety: auto-reset if recording has been running too long
    if _phase != 0 and (time.monotonic() - _started_at) > _MAX_DURATION:
        log.warning(
            "Memory recording timed out, resetting",
            extra={"duration": _MAX_DURATION, "pid": pid},
        )
        _reset()

    if _phase == 0:
        # Phase 1: start tracemalloc, take baseline snapshot
        gc.collect()
        tracemalloc.start(1)
        _snapshot_a = tracemalloc.take_snapshot()
        _rss_start = _rss_bytes()
        _started_at = time.monotonic()
        _phase = 1
        log.info(
            "Memory recording STARTED",
            extra={"pid": pid, "rss_mb": round(_rss_start / (1024 * 1024), 1)},
        )

    elif _phase == 1:
        # Phase 2: take midpoint snapshot
        gc.collect()
        _snapshot_b = tracemalloc.take_snapshot()
        _phase = 2
        log.info("Memory recording MIDPOINT", extra={"pid": pid})

    elif _phase == 2:
        # Phase 3: take final snapshot, compute intersection, write results
        gc.collect()
        snapshot_c = tracemalloc.take_snapshot()
        tracemalloc.stop()
        rss_end = _rss_bytes()
        duration = time.monotonic() - _started_at

        # Compare B-A and C-B
        if _snapshot_a is None or _snapshot_b is None:
            log.error(
                "Memory recording in bad state, resetting",
                extra={"pid": pid},
            )
            _reset()
            return
        first_half = _snapshot_b.compare_to(_snapshot_a, "lineno")
        second_half = snapshot_c.compare_to(_snapshot_b, "lineno")

        grew_first = _growers_by_lineno(first_half)
        grew_second = _growers_by_lineno(second_half)

        # Intersection: only lines that grew in BOTH halves
        common_keys = grew_first.keys() & grew_second.keys()
        leaks = [
            {
                "file": fn,
                "line": line,
                "size_first": grew_first[(fn, line)],
                "size_second": grew_second[(fn, line)],
            }
            for fn, line in common_keys
        ]
        leaks.sort(key=lambda x: x["size_second"], reverse=True)

        result = {
            "pid": pid,
            "duration": round(duration, 1),
            "rss_before": _rss_start,
            "rss_after": rss_end,
            "leaks": leaks[:30],
        }

        output_path = profile_path(pid)
        tmp_path = output_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(result, f)
        os.replace(tmp_path, output_path)

        log.info(
            "Memory recording STOPPED",
            extra={
                "pid": pid,
                "duration_s": round(duration),
                "rss_before_mb": round(_rss_start / (1024 * 1024), 1),
                "rss_after_mb": round(rss_end / (1024 * 1024), 1),
                "suspected_leaks": len(leaks),
                "profile": output_path,
            },
        )

        _reset()
