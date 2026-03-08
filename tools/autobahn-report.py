"""Parse Autobahn testsuite results and print a summary.

Usage:
    python scripts/autobahn-report.py <results-dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m~\033[0m"
INFO = "\033[34mi\033[0m"

# Behaviors that count as passing
OK_BEHAVIORS = {"OK", "INFORMATIONAL", "NON-STRICT"}


def main() -> None:
    results_dir = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scratch/autobahn-results")
    )

    # Find the index JSON (autobahn names it after the server agent)
    index_files = list(results_dir.glob("index.json"))
    if not index_files:
        # Try the server-named directory
        for subdir in results_dir.iterdir():
            if subdir.is_dir() and subdir.name != "__pycache__":
                index_files = list(subdir.glob("*.json"))
                break

    # The main summary is in index.json
    index_path = results_dir / "index.json"
    if not index_path.exists():
        print(f"No index.json found in {results_dir}")
        print("Looking for result files...")
        # Autobahn puts results in a directory named after the agent
        for p in sorted(results_dir.rglob("*.json")):
            if p.name != "fuzzingclient.json":
                print(f"  {p}")
        sys.exit(1)

    with open(index_path) as f:
        index = json.load(f)

    # index.json format: {"Plain": {"1.1.1": {"behavior": "OK", ...}, ...}}
    total = 0
    passed = 0
    failed = 0
    non_strict = 0
    informational = 0
    failed_cases: list[tuple[str, str]] = []
    current_group = ""

    for agent, cases in index.items():
        print(f"\033[1mAgent: {agent}\033[0m\n")

        for case_id in sorted(cases.keys(), key=_sort_key):
            result = cases[case_id]
            behavior = result.get("behavior", "UNKNOWN")
            total += 1

            # Print group headers
            group = case_id.split(".")[0]
            if group != current_group:
                current_group = group
                group_name = _group_name(group)
                print(f"\n\033[1m{group_name}\033[0m")

            if behavior == "OK":
                passed += 1
                icon = PASS
            elif behavior == "NON-STRICT":
                non_strict += 1
                passed += 1  # non-strict counts as pass
                icon = WARN
            elif behavior == "INFORMATIONAL":
                informational += 1
                passed += 1
                icon = INFO
            else:
                failed += 1
                icon = FAIL
                close_code = result.get("remoteCloseCode", "")
                failed_cases.append((case_id, f"{behavior} (close: {close_code})"))

            desc = result.get("description", case_id)
            # Truncate long descriptions
            if len(desc) > 70:
                desc = desc[:67] + "..."
            print(f"  {icon} {case_id}: {desc}")

    print(f"\n{'─' * 60}")
    color = "\033[32m" if failed == 0 else "\033[31m"
    print(f"{color}{passed}/{total} passed\033[0m", end="")
    if non_strict:
        print(f" ({non_strict} non-strict)", end="")
    if informational:
        print(f" ({informational} informational)", end="")
    print()

    if failed_cases:
        print(f"\n\033[31m{failed} failed:\033[0m")
        for case_id, detail in failed_cases:
            print(f"  {case_id}: {detail}")

    sys.exit(1 if failed > 0 else 0)


def _sort_key(case_id: str) -> list[int]:
    """Sort case IDs numerically (1.1.1 before 1.1.10)."""
    parts = []
    for part in case_id.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return parts


def _group_name(group: str) -> str:
    """Human-readable names for autobahn test case groups."""
    names = {
        "1": "Framing (1.x)",
        "2": "Pings/Pongs (2.x)",
        "3": "Reserved Bits (3.x)",
        "4": "Opcodes (4.x)",
        "5": "Fragmentation (5.x)",
        "6": "UTF-8 Handling (6.x)",
        "7": "Close Handling (7.x)",
        "9": "Limits/Performance (9.x)",
        "10": "Misc (10.x)",
        "12": "WebSocket Compression (12.x)",
        "13": "WebSocket Compression (13.x)",
    }
    return names.get(group, f"Group {group}")


if __name__ == "__main__":
    main()
