from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ("Invalid",)


@dataclass(frozen=True)
class Invalid:
    """A failed validation result.

    `errors` maps field names to lists of error messages. The special key
    `"__all__"` holds non-field (cross-field) errors. `raw` is the original
    input — preserved so callers can re-render forms with the user's
    submitted values alongside the errors.
    """

    errors: dict[str, list[str]]
    raw: dict[str, Any]
