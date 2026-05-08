from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ("Valid", "Invalid")


@dataclass(frozen=True)
class Valid[T]:
    """A successful validation result.

    `data` is the typed schema instance with cleaned field values. `raw` is the
    original input dict, preserved for re-rendering forms with the user's
    submitted values.
    """

    data: T
    raw: dict[str, Any]


@dataclass(frozen=True)
class Invalid:
    """A failed validation result.

    `errors` maps field names to lists of error messages. The special key
    `"__all__"` holds non-field (cross-field) errors. `raw` is the original
    input.
    """

    errors: dict[str, list[str]]
    raw: dict[str, Any]
