from __future__ import annotations

import os


def get_cpu_count() -> int:
    """Get the number of CPUs available, respecting cgroup limits in containers.

    os.process_cpu_count() only checks sched_getaffinity, not cgroup CPU quotas,
    so containers often see the host's full CPU count. This reads the cgroup v2
    quota file to detect the actual limit.

    Can be removed when minimum Python version is 3.14+ (cpython#120078).
    """
    cpu_count = os.process_cpu_count() or 1

    # Resolve the process's own cgroup path for nested cgroup v2 hierarchies
    # (e.g. systemd units, containers without a private cgroup namespace)
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

    return cpu_count
