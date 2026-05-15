"""Disk cache for compiled `.html` templates.

Lives at `<project>/.plain/html/` by default; override the location with
the `HTML_CACHE_DIR` setting, or disable the disk cache entirely with
`HTML_CACHE_DISABLED = True`. Both can also be set via Plain's standard
`PLAIN_*` env-var prefix (`PLAIN_HTML_CACHE_DIR`, `PLAIN_HTML_CACHE_DISABLED`).
Files are named `<key>__<source-name>.py` — the hash makes the cache
content-addressable, the human-readable suffix makes the dir greppable.

Cache key inputs:
  - Source SHA-256
  - Compiler version constant
  - Transitive `:include` children's cache keys
  - `imports:` modules' file mtimes (when resolvable)

Writes are atomic (tmp + fsync + rename in the same directory) so a
crashed process can't leave a partial file behind. The cache dir is
created mode `0700` — its contents are Python that gets `exec`'d, so
anyone with write access to it owns the rendering process.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
from pathlib import Path

from plain.runtime import settings

# Bump on codegen changes so stale cache entries get rebuilt automatically.
COMPILER_VERSION = 6

# Tracks which cache roots this process has already `mkdir`'d, so we skip
# the syscall on every subsequent compile. Settings reads in `cache_root()`
# are cheap; the `mkdir` is what dominates per-template compile cost.
_ensured_dirs: set[Path] = set()


def cache_root() -> Path | None:
    """Return the disk cache root, or `None` if disabled.

    Reads `HTML_CACHE_DISABLED` and `HTML_CACHE_DIR` from Plain settings
    (overridable via `PLAIN_HTML_CACHE_DISABLED` / `PLAIN_HTML_CACHE_DIR`
    environment variables). When `HTML_CACHE_DIR` is unset, defaults to
    `<project>/.plain/html/` via Plain's `PLAIN_TEMP_PATH` convention
    (same dir-shape as `.plain/assets/compiled`, `.plain/dev/logs`, etc.).
    """
    if settings.HTML_CACHE_DISABLED:
        return None
    if settings.HTML_CACHE_DIR is not None:
        return Path(settings.HTML_CACHE_DIR)
    try:
        from plain.runtime import PLAIN_TEMP_PATH

        return Path(PLAIN_TEMP_PATH) / "html"
    except Exception:
        return None


def ensure_cache_dir(root: Path) -> Path:
    """Create the cache root with restrictive permissions.

    Existing dirs aren't re-chmodded — that's the operator's call, not
    something a library should silently change. The `mkdir` syscall is
    skipped on repeat calls for the same root.
    """
    if root not in _ensured_dirs:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ensured_dirs.add(root)
    return root


def cache_file_for(key: str, source_path: Path) -> Path | None:
    """Return the on-disk path for a cache entry, or `None` if caching
    is disabled.

    Cache entries are marshalled Python code objects (`.pyc`-style).
    The naming pattern is `<key>__<source-name>.pyc` so the hash makes
    the cache content-addressable and the human-readable suffix makes
    the dir greppable.
    """
    root = cache_root()
    if root is None:
        return None
    ensure_cache_dir(root)
    safe_name = source_path.name.replace(os.sep, "_")
    return root / f"{key}__{safe_name}.pyc"


def compute_cache_key(
    source: str,
    child_keys: list[str],
    imports_mtimes_map: dict[str, int],
) -> str:
    """Hash all the inputs that should invalidate the compiled output."""
    h = hashlib.sha256()
    h.update(COMPILER_VERSION.to_bytes(2, "big"))
    h.update(source.encode("utf-8"))
    h.update(b"\n--includes--\n")
    for k in sorted(child_keys):
        h.update(k.encode("ascii"))
        h.update(b"\n")
    h.update(b"--imports--\n")
    for mod in sorted(imports_mtimes_map):
        h.update(f"{mod}={imports_mtimes_map[mod]}\n".encode())
    return h.hexdigest()[:16]


def write_atomic_bytes(path: Path, content: bytes) -> None:
    """Write `content` to `path` without leaving a half-written file.

    Tmp file in the same directory + fsync + atomic rename. The
    per-PID suffix keeps two parallel workers from clobbering each
    other's tmp file mid-write.
    """
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def imports_mtimes(stmts: list[str]) -> dict[str, int]:
    """Resolve each `imports:` statement to file mtimes so a Python-side
    edit invalidates downstream cache entries.

    For each import, the *most-specific* dotted candidate is recorded —
    e.g. `from app.users.models import Task` records `app.users.models`,
    not just `app`. `module_mtime_ns` then walks the dotted path from
    the right, so a candidate that doesn't resolve falls back to the
    nearest package that does.

    Modules whose source can't be located (builtins, frozen, namespace
    packages, anything `importlib` can't `find_spec` for) get `0` —
    same value every time, so the key stays stable rather than
    chasing import-resolution noise.
    """
    out: dict[str, int] = {}
    for stmt in stmts:
        try:
            tree = ast.parse(stmt, mode="exec")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                # `import a.b.c` / `import a.b.c as x` → record `a.b.c`.
                for alias in node.names:
                    candidates.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # The from-target itself, plus each imported name as a
                    # potential submodule (`from a.b import c` may import
                    # the submodule `a.b.c` — record that and let
                    # `module_mtime_ns` walk back to `a.b` on failure).
                    candidates.append(node.module)
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        candidates.append(f"{node.module}.{alias.name}")
            for candidate in candidates:
                if candidate in out:
                    continue
                out[candidate] = module_mtime_ns(candidate)
    return out


def module_mtime_ns(mod_name: str) -> int:
    """Return the mtime (nanoseconds) of `mod_name`'s source, walking the
    dotted path from the right so `app.users.models` falls back to
    `app.users` and then `app` if the more-specific candidate isn't
    importable on its own. Returns `0` if nothing in the chain resolves.
    """
    parts = mod_name.split(".")
    while parts:
        candidate = ".".join(parts)
        try:
            spec = importlib.util.find_spec(candidate)
        except (ImportError, ValueError):
            spec = None
        if spec is not None and spec.origin and spec.origin != "built-in":
            try:
                return os.stat(spec.origin).st_mtime_ns
            except OSError:
                return 0
        parts.pop()
    return 0
