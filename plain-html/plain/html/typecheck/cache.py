"""Per-template typecheck result cache.

The synthesis + subprocess loop is expensive at repo scale, but it's
deterministic in a small set of inputs. We hash those inputs into a
cache key; a hit returns the previously recorded diagnostics, a miss
runs the backend and stores the result.

Cache lives under `.plain/html/typecheck/` — the framework-wide temp
directory other tools (assets manifest, email previews, dev services)
already use. Each entry is a small JSON file named by the key. Wiping
the directory is always safe.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from dataclasses import asdict
from pathlib import Path

from plain.runtime import PLAIN_TEMP_PATH

from .declarations import Declarations
from .synth import FORMAT_VERSION


def _default_cache_root() -> Path:
    return PLAIN_TEMP_PATH / "html" / "typecheck"


def cache_key(
    *,
    source: str,
    declarations: Declarations,
    backend_name: str,
    backend_version: str,
) -> str:
    """Build the hash key for this template's typecheck result.

    Inputs:
    - the raw template source (frontmatter + body)
    - the mtime of every module referenced in `imports:` and in `attrs:`
      type expressions (so editing a referenced model invalidates the
      cached result)
    - the backend name + version
    - the synthesis format version (bumped when synth.py output changes)
    """
    h = hashlib.sha256()
    h.update(b"plain.html.typecheck\n")
    h.update(f"format={FORMAT_VERSION}\n".encode())
    h.update(f"backend={backend_name}:{backend_version}\n".encode())
    h.update(b"source=")
    h.update(source.encode("utf-8"))
    h.update(b"\n")

    for module_name in sorted(_referenced_modules(declarations)):
        h.update(f"module={module_name}:{_module_mtime(module_name)}\n".encode())

    return h.hexdigest()


def load(key: str, *, root: Path | None = None) -> list[dict] | None:
    """Return cached diagnostics for `key`, or None on miss."""
    path = _entry_path(key, root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def store(key: str, diagnostics: list, *, root: Path | None = None) -> None:
    """Store diagnostics for `key`. `diagnostics` is a list of dataclasses."""
    path = _entry_path(key, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(d) for d in diagnostics]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def _entry_path(key: str, root: Path | None) -> Path:
    base = root if root is not None else _default_cache_root()
    return base / f"{key}.json"


def _referenced_modules(declarations: Declarations) -> set[str]:
    """Return the top-level dotted names of every module the template depends on."""
    names: set[str] = set()
    for imp in declarations.imports:
        try:
            tree = ast.parse(imp.statement, mode="exec")
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)

    for attr in declarations.attrs:
        names.update(_modules_in_type_expr(attr.type_source))
    for slot in declarations.slots:
        if slot.yields_source is not None:
            names.update(_modules_in_type_expr(slot.yields_source))

    return names


def _modules_in_type_expr(source: str) -> set[str]:
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree.body):
        if isinstance(node, ast.Attribute):
            chain = _dotted(node)
            if chain and len(chain) >= 2:
                out.add(".".join(chain[:-1]))
    return out


def _dotted(node: ast.Attribute) -> list[str] | None:
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    parts.reverse()
    return parts


def _module_mtime(name: str) -> int:
    """Return the mtime of `name`'s source file, or 0 if not resolvable.

    Walks the dotted name from the right, so `app.users.User` falls back to
    `app.users` and then `app`. Failure is silent on purpose: missing
    modules will surface as ty errors during the check.
    """
    parts = name.split(".")
    while parts:
        candidate = ".".join(parts)
        try:
            spec = importlib.util.find_spec(candidate)
        except (ImportError, ValueError):
            spec = None
        if spec is not None and spec.origin and spec.origin != "built-in":
            try:
                return int(Path(spec.origin).stat().st_mtime_ns)
            except OSError:
                return 0
        parts.pop()
    return 0
