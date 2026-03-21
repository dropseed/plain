from __future__ import annotations

import os
import resource
import sys
import threading
import time
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_cgroup_dir() -> str:
    """Resolve the process's own cgroup directory for cgroup v2.

    Cached because the cgroup path is static for the lifetime of the process.
    """
    cgroup_dir = "/sys/fs/cgroup"
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                # cgroup v2 entries have the form "0::<path>"
                parts = line.strip().split(":", 2)
                if (
                    len(parts) == 3
                    and parts[0] == "0"
                    and parts[1] == ""
                    and parts[2] != "/"
                ):
                    cgroup_dir = f"/sys/fs/cgroup{parts[2]}"
                    break
    except (FileNotFoundError, IndexError, OSError):
        pass
    return cgroup_dir


def get_rss_bytes() -> int:
    """Get the current process's RSS in bytes.

    Uses /proc/self/statm on Linux for current RSS,
    falls back to ru_maxrss (peak RSS) on macOS.
    """
    if sys.platform == "linux":
        try:
            with open("/proc/self/statm") as f:
                resident_pages = int(f.read().split()[1])
            return resident_pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            pass

    # macOS / fallback: ru_maxrss is peak, not current
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return rusage.ru_maxrss  # bytes on macOS
    return rusage.ru_maxrss * 1024  # KB on Linux (fallback)


def get_cpu_count() -> int:
    """Get the number of CPUs available, respecting cgroup limits in containers.

    os.process_cpu_count() only checks sched_getaffinity, not cgroup CPU quotas,
    so containers often see the host's full CPU count. This reads the cgroup v2
    quota file to detect the actual limit.

    Can be removed when minimum Python version is 3.14+ (cpython#120078).
    """
    cpu_count = os.process_cpu_count() or 1

    cgroup_dir = _get_cgroup_dir()

    # Check cgroup v2 CPU quota (Docker, Kubernetes, Railway, etc.)
    try:
        with open(f"{cgroup_dir}/cpu.max") as f:
            parts = f.read().strip().split()
            if len(parts) >= 2 and parts[0] != "max":
                quota = int(parts[0])
                period = int(parts[1])
                cgroup_cpus = max(1, -(-quota // period))  # ceiling division
                cpu_count = min(cpu_count, cgroup_cpus)
    except (FileNotFoundError, ValueError, OSError):
        pass

    # Check cgroup v1 CPU quota (Heroku Cedar, older Docker, etc.)
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read().strip())
        if quota > 0:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
                period = int(f.read().strip())
            cgroup_cpus = max(1, -(-quota // period))
            cpu_count = min(cpu_count, cgroup_cpus)
    except (FileNotFoundError, ValueError, OSError):
        pass

    return cpu_count


def get_memory_usage() -> tuple[int, int | None]:
    """Get memory usage and optional limit in bytes, container-aware.

    Returns (usage_bytes, limit_bytes) for containers with cgroup limits,
    or (usage_bytes, None) for bare-metal/dev where only process RSS is available.

    Tries cgroup v2 first, then v1, then falls back to process RSS via getrusage.
    """
    cgroup_dir = _get_cgroup_dir()

    # cgroup v2
    try:
        with open(f"{cgroup_dir}/memory.current") as f:
            usage = int(f.read().strip())
        with open(f"{cgroup_dir}/memory.max") as f:
            content = f.read().strip()
            limit = None if content == "max" else int(content)
        return (usage, limit)
    except (FileNotFoundError, ValueError, OSError):
        pass

    # cgroup v1
    try:
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
            usage = int(f.read().strip())
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
            limit = int(f.read().strip())
            # cgroup v1 uses a very large number to mean "unlimited"
            if limit >= 2**62:
                limit = None
        return (usage, limit)
    except (FileNotFoundError, ValueError, OSError):
        pass

    # Fallback: process RSS (works on macOS and Linux)
    return (get_rss_bytes(), None)


_cpu_lock = threading.Lock()
_last_cpu_time: float = 0.0
_last_wall_time: float = 0.0


def get_process_cpu_percent() -> int | None:
    """Get this process's CPU usage as a percentage of wall-clock time.

    Uses resource.getrusage() which reports actual CPU time consumed,
    accurate in both containers and on bare metal.

    Returns None on the first call (no baseline to compare against).
    Subsequent calls return the CPU percent since the previous call.
    """
    global _last_cpu_time, _last_wall_time

    usage = resource.getrusage(resource.RUSAGE_SELF)
    cpu_time = usage.ru_utime + usage.ru_stime
    wall_time = time.monotonic()

    with _cpu_lock:
        if _last_wall_time == 0.0:
            _last_cpu_time = cpu_time
            _last_wall_time = wall_time
            return None

        wall_delta = wall_time - _last_wall_time
        cpu_delta = cpu_time - _last_cpu_time

        _last_cpu_time = cpu_time
        _last_wall_time = wall_time

    if wall_delta <= 0:
        return 0

    return min(round(cpu_delta / wall_delta * 100), 100)
