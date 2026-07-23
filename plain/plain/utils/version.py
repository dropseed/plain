from __future__ import annotations

import re


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string into a tuple of integers for comparison.

    Lenient on purpose — callers compare versions people typed into config
    files, so a string we can't fully parse should sort rather than raise: a
    leading `v` is dropped, and each dot-separated segment contributes its
    leading integer (`0-rc` → `0`), or `0` if it has none.

    This only understands release versions. A pre-release like `1.75.0-rc.1`
    parses to `(1, 75, 0, 1)` and so sorts *after* `1.75.0` — fine for the
    release-to-release comparisons here, wrong if you need PEP 440 ordering.
    """
    clean_version = version_str.lstrip("v")
    parts = []
    for part in clean_version.split("."):
        numeric_part = re.match(r"\d+", part)
        parts.append(int(numeric_part.group()) if numeric_part else 0)
    return tuple(parts)


def compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings: -1 if v1 < v2, 0 if equal, 1 if v1 > v2.

    The shorter side is zero-padded, so `1.75` compares equal to `1.75.0`
    rather than older than it.
    """
    parsed_v1 = parse_version(v1)
    parsed_v2 = parse_version(v2)

    max_len = max(len(parsed_v1), len(parsed_v2))
    parsed_v1 += (0,) * (max_len - len(parsed_v1))
    parsed_v2 += (0,) * (max_len - len(parsed_v2))

    if parsed_v1 < parsed_v2:
        return -1
    elif parsed_v1 > parsed_v2:
        return 1
    else:
        return 0
