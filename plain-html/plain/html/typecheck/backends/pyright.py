"""Pyright backend — fallback when ty isn't available."""

from __future__ import annotations

import json
import shutil
import subprocess
from functools import cached_property
from pathlib import Path

from .base import Backend, BackendDiagnostic, BackendError


class PyrightBackend(Backend):
    name = "pyright"

    @cached_property
    def version(self) -> str:
        executable = self._executable()
        try:
            proc = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError(f"Failed to query pyright version: {e}") from e
        out = (proc.stdout or proc.stderr).strip()
        return out or "unknown"

    def check_file(self, synth_path: Path) -> list[BackendDiagnostic]:
        executable = self._executable()
        try:
            proc = subprocess.run(
                [executable, "--outputjson", str(synth_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError(f"Failed to run pyright: {e}") from e

        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as e:
            raise BackendError(f"pyright produced non-JSON output: {e}") from e

        diagnostics: list[BackendDiagnostic] = []
        for item in data.get("generalDiagnostics", []):
            range_ = item.get("range") or {}
            start = range_.get("start") or {}
            # Pyright uses 0-indexed lines/columns. Normalize to 1-indexed
            # so we match ty.
            line = int(start.get("line", 0)) + 1
            column = int(start.get("character", 0)) + 1
            diagnostics.append(
                BackendDiagnostic(
                    line=line,
                    column=column,
                    severity=item.get("severity", "error"),
                    code=item.get("rule") or "type-error",
                    message=item.get("message", "").strip(),
                )
            )
        return diagnostics

    def _executable(self) -> str:
        path = shutil.which("pyright")
        if not path:
            raise BackendError(
                "pyright is not installed; install it with `uv tool install pyright` "
                "or use the ty backend"
            )
        return path
