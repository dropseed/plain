"""`validate()`'s failure types — pure data, no rendering.

`Invalid` is the failure result: a flat list of `Error`s plus the raw
input. (`Form` itself is the success result — see `forms.py`.) Rendering
either to HTML is a template-layer concern, not theirs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ("Error", "Invalid")


@dataclass(frozen=True)
class Error:
    """One validation error.

    `message` is human-readable. `code` is a stable machine identifier —
    `"required"`, `"invalid"`, `"invalid_choice"`, … — so an error can be
    matched in code or a test without depending on the exact wording.
    `field` names the field the error concerns, or is `None` for a
    form-level error (a cross-field `check()` failure, say).
    """

    message: str
    code: str
    field: str | None = None


@dataclass(frozen=True)
class Invalid:
    """A failed validation result — pure data.

    `errors` is one flat list: each `Error` carries its own `field`, so
    there is no keyed structure to walk and no `"__all__"` sentinel.
    `raw` is the original submitted input, kept so a re-render can show
    the user what they typed.

    `Invalid` is falsy and a `Form` instance is truthy, so a caller
    branches on the `validate()` result with `if not result:` — the
    failure arm is then type-narrowed to `Invalid`.
    """

    errors: list[Error]
    raw: dict[str, Any]

    def __bool__(self) -> Literal[False]:
        """Always falsy — `Invalid` is the failure arm of `validate()`."""
        return False
