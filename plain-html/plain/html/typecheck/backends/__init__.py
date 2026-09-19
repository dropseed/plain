"""Type-checker backends — adapters that translate diagnostics from an
external tool (ty, pyright) into a uniform `BackendDiagnostic` shape.

Each backend takes the path to a synthesized Python file and returns a
list of diagnostics keyed on the file's own line/column numbers. The
checker re-anchors those positions to the original template using the
synth source map.
"""

from __future__ import annotations

from .base import Backend, BackendDiagnostic, BackendError
from .pyright import PyrightBackend
from .ty import TyBackend

__all__ = [
    "Backend",
    "BackendDiagnostic",
    "BackendError",
    "PyrightBackend",
    "TyBackend",
    "resolve",
]


def resolve(name: str | None) -> Backend:
    """Return a backend instance by name. Defaults to ty."""
    selected = (name or "ty").lower()
    if selected == "ty":
        return TyBackend()
    if selected == "pyright":
        return PyrightBackend()
    raise BackendError(f"Unknown typecheck backend: {name!r}")
