"""ty backend — runs `ty check --output-format concise` on a file."""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import cached_property
from pathlib import Path

from .base import Backend, BackendDiagnostic, BackendError

# `path:line:col: severity[code] message`
_CONCISE_LINE = re.compile(
    r"""
    ^(?P<path>[^:]+):
    (?P<line>\d+):
    (?P<col>\d+):\s*
    (?P<severity>[a-z]+)
    \[(?P<code>[^\]]+)\]\s*
    (?P<message>.*)$
    """,
    re.VERBOSE,
)


class TyBackend(Backend):
    name = "ty"

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
            raise BackendError(f"Failed to query ty version: {e}") from e
        out = (proc.stdout or proc.stderr).strip()
        return out or "unknown"

    def check_file(self, synth_path: Path) -> list[BackendDiagnostic]:
        executable = self._executable()
        try:
            proc = subprocess.run(
                [
                    executable,
                    "check",
                    "--output-format",
                    "concise",
                    "--no-respect-ignore-files",
                    str(synth_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise BackendError(f"Failed to run ty: {e}") from e

        # ty exits non-zero when diagnostics are reported. Anything weirder
        # (panic, missing arg) lands on stderr without a parseable line.
        diagnostics: list[BackendDiagnostic] = []
        for line in proc.stdout.splitlines():
            match = _CONCISE_LINE.match(line)
            if not match:
                continue
            # Filter out diagnostics for files other than the one we asked
            # about — ty can complain about imports, but we only care
            # about the synth file itself for now.
            if Path(match.group("path")).resolve() != synth_path.resolve():
                continue
            diagnostics.append(
                BackendDiagnostic(
                    line=int(match.group("line")),
                    column=int(match.group("col")),
                    severity=match.group("severity"),
                    code=match.group("code"),
                    message=match.group("message").strip(),
                )
            )
        return diagnostics

    def _executable(self) -> str:
        path = shutil.which("ty")
        if not path:
            raise BackendError(
                "ty is not installed; install it with `uv tool install ty` "
                "or pick another backend"
            )
        return path
