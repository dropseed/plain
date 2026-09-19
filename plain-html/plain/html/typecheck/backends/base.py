"""Shared base for typecheck backends."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class BackendError(Exception):
    pass


@dataclass
class BackendDiagnostic:
    """One diagnostic from a typecheck backend.

    Positions refer to the synthesized file the backend ran against.
    Code/severity follow the backend's native vocabulary (mostly common
    enough across ty and pyright to be useful without translation).
    """

    line: int
    column: int
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str


class Backend(Protocol):
    """The contract a typecheck backend implements."""

    name: str
    version: str

    def check_file(self, synth_path: Path) -> list[BackendDiagnostic]:
        """Run the backend against `synth_path`, return its diagnostics."""
        ...
