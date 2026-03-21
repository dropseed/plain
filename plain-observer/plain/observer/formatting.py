from __future__ import annotations


def format_bytes(size: int, precision: int = 1) -> str:
    """Format a byte count as a human-readable string."""
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.{precision}f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.{precision}f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.{precision}f} KB"
    return f"{size} B"
