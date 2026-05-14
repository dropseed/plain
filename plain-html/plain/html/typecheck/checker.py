"""Top-level orchestration for the typecheck pass.

Drives the pipeline: split frontmatter → validate declarations →
synthesize a Python module → run backend → map diagnostics back to
template positions. Wraps each step in caching so repeat runs are cheap.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from plain.runtime import PLAIN_TEMP_PATH

from .. import frontmatter as fm
from . import cache
from .backends import Backend, BackendDiagnostic, BackendError, resolve
from .declarations import DeclarationError
from .declarations import parse as parse_declarations
from ..positions import body_offset, offset_to_line_col
from .synth import SourceMapEntry, Synthesis, synthesize


@dataclass
class TypecheckError:
    """A type-check diagnostic, anchored at a template position."""

    path: Path | None
    line: int
    column: int
    severity: str
    code: str
    message: str
    kind: str  # the source-map kind: "expr", "if", "for-iter", etc.

    def format(self) -> str:
        label = str(self.path) if self.path else "<stdin>"
        return f"{label}:{self.line}:{self.column}: {self.severity}[{self.code}] {self.message}"


def check_path(
    path: Path,
    *,
    backend: Backend | None = None,
    use_cache: bool = True,
    cache_root: Path | None = None,
) -> list[TypecheckError]:
    """Run the typecheck pass against a single template file."""
    source = path.read_text(encoding="utf-8")
    return check_source(
        source,
        path=path,
        backend=backend,
        use_cache=use_cache,
        cache_root=cache_root,
    )


def check_source(
    source: str,
    *,
    path: Path | None = None,
    backend: Backend | None = None,
    use_cache: bool = True,
    cache_root: Path | None = None,
) -> list[TypecheckError]:
    """Run the typecheck pass against an in-memory template source."""
    try:
        fmdict, body = fm.split(source)
    except Exception as e:
        return [_decl_error(path, source, str(e))]

    try:
        declarations = parse_declarations(fmdict)
    except DeclarationError as e:
        return [_decl_error(path, source, str(e))]

    active_backend = (
        backend
        if backend is not None
        else resolve(os.environ.get("PLAIN_HTML_TYPECHECK_BACKEND"))
    )

    key = cache.cache_key(
        source=source,
        declarations=declarations,
        backend_name=active_backend.name,
        backend_version=active_backend.version,
    )

    if use_cache:
        cached = cache.load(key, root=cache_root)
        if cached is not None:
            return [_from_cache(entry, path) for entry in cached]

    synth = synthesize(body, declarations)
    diagnostics = _run_backend(active_backend, synth)
    errors = _map_diagnostics(diagnostics, synth, source, path)

    if use_cache:
        cache.store(
            key,
            [_to_cache(e) for e in errors],
            root=cache_root,
        )

    return errors


def _run_backend(backend: Backend, synth: Synthesis) -> list[BackendDiagnostic]:
    # Write the synth file inside the project tree (under `.plain/`) so the
    # backend's project / Python-environment discovery picks up the right
    # pyproject.toml and `.venv`. A tempfile in `/var/folders/...` makes ty
    # fall back to the system Python and silently degrade resolved types
    # (`app.tasks.models.Task` → `Unknown` → spurious diagnostics).
    workdir = PLAIN_TEMP_PATH / "html" / "typecheck-work"
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".py",
        prefix="plain_html_typecheck_",
        dir=workdir,
        delete=False,
    ) as tmp:
        tmp.write(synth.source)
        tmp_path = Path(tmp.name)
    try:
        return backend.check_file(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _map_diagnostics(
    diagnostics: list[BackendDiagnostic],
    synth: Synthesis,
    source: str,
    path: Path | None,
) -> list[TypecheckError]:
    out: list[TypecheckError] = []
    boffset = body_offset(source)
    for diag in diagnostics:
        entry = synth.line_map.get(diag.line)
        if entry is None:
            # Diagnostic landed on a synth line that isn't a tracked
            # expression (a synthetic helper line, a missing-import error,
            # etc.). Skip — those don't belong to the user.
            continue
        line, column = offset_to_line_col(source, boffset + entry.template_offset)
        out.append(
            TypecheckError(
                path=path,
                line=line,
                column=column,
                severity=diag.severity,
                code=diag.code,
                message=diag.message,
                kind=entry.kind,
            )
        )
    return out


def _to_cache(e: TypecheckError) -> _CacheEntry:
    return _CacheEntry(
        line=e.line,
        column=e.column,
        severity=e.severity,
        code=e.code,
        message=e.message,
        kind=e.kind,
    )


def _from_cache(entry: dict, path: Path | None) -> TypecheckError:
    return TypecheckError(
        path=path,
        line=int(entry["line"]),
        column=int(entry["column"]),
        severity=str(entry["severity"]),
        code=str(entry["code"]),
        message=str(entry["message"]),
        kind=str(entry.get("kind", "expr")),
    )


def _decl_error(path: Path | None, source: str, message: str) -> TypecheckError:
    """Frontmatter / declaration errors anchor at the start of the file."""
    return TypecheckError(
        path=path,
        line=1,
        column=1,
        severity="error",
        code="frontmatter",
        message=message,
        kind="declaration",
    )


@dataclass
class _CacheEntry:
    """Same shape as TypecheckError minus `path`; what we actually persist."""

    line: int
    column: int
    severity: str
    code: str
    message: str
    kind: str


__all__ = [
    "BackendError",
    "SourceMapEntry",
    "Synthesis",
    "TypecheckError",
    "check_path",
    "check_source",
]
