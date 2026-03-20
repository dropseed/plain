"""Subprocess script for measuring boot-time memory baseline.

Invoked by `plain memory` in a fresh process so RSS measurements
are accurate — no prior imports contaminate the numbers.

Outputs a single JSON line to stdout.
"""

from __future__ import annotations

import json
import resource
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed


def _rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return r.ru_maxrss / (1024 * 1024)
    return r.ru_maxrss / 1024


def _measure_package(pkg: str) -> tuple[str, float] | None:
    """Measure RSS cost of importing a single package in isolation."""
    if not pkg.isidentifier():
        return None
    try:
        out = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import resource, sys\n"
                    "r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
                    f"import {pkg}\n"
                    "r1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n"
                    "d = (r1 - r0) / (1024*1024) if sys.platform == 'darwin'"
                    " else (r1 - r0) / 1024\n"
                    "print(round(d, 1))\n"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            pkg_mb = float(out.stdout.strip())
            if pkg_mb >= 1.0:
                return (pkg, pkg_mb)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def main() -> None:
    import plain.runtime

    plain.runtime.setup()

    rss = _rss_mb()

    # Count modules by top-level package
    packages: Counter[str] = Counter()
    for mod in sys.modules:
        packages[mod.split(".")[0]] += 1

    # Identify heavy packages to measure individually.
    stdlib = sys.stdlib_module_names | {"_"}
    heavy_packages = [
        pkg
        for pkg, count in packages.most_common()
        if count >= 10 and pkg not in stdlib and pkg.isidentifier()
    ]

    # Measure per-package RSS in parallel subprocesses.
    pkg_rss: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_measure_package, pkg): pkg for pkg in heavy_packages[:15]
        }
        for future in as_completed(futures):
            result = future.result()
            if result:
                pkg_rss[result[0]] = result[1]

    output = {
        "rss": rss,
        "modules": len(sys.modules),
        "packages": sorted(pkg_rss.items(), key=lambda x: x[1], reverse=True),
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
