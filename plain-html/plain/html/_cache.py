"""Disk cache for compiled `.html` templates.

Lives at `<project>/.plain/html/` by default; override with
`PLAIN_HTML_CACHE_DIR`. Files are named `<key>__<source-name>.py` —
the hash makes the cache content-addressable, the human-readable
suffix makes the dir greppable.

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

# Bump on codegen changes so stale cache entries get rebuilt automatically.
COMPILER_VERSION = 2


def cache_root() -> Path | None:
    """Return the disk cache root, or `None` if disabled.

    Defaults to `<cwd>/.plain/html/` via Plain's `PLAIN_TEMP_PATH`
    convention (same dir-shape as `.plain/assets/compiled`,
    `.plain/dev/logs`, etc.). Override with `PLAIN_HTML_CACHE_DIR`;
    set that env var to an empty string to disable the disk cache.
    """
    env = os.environ.get("PLAIN_HTML_CACHE_DIR")
    if env is not None:
        if env == "":
            return None
        return Path(env)
    try:
        from plain.runtime import PLAIN_TEMP_PATH

        return Path(PLAIN_TEMP_PATH) / "html"
    except Exception:
        return None


def ensure_cache_dir(root: Path) -> Path:
    """Create the cache root with restrictive permissions.

    Existing dirs aren't re-chmodded — that's the operator's call, not
    something a library should silently change.
    """
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def cache_file_for(key: str, source_path: Path) -> Path | None:
    """Return the on-disk path for a cache entry, or `None` if caching
    is disabled.
    """
    root = cache_root()
    if root is None:
        return None
    ensure_cache_dir(root)
    safe_name = source_path.name.replace(os.sep, "_")
    return root / f"{key}__{safe_name}.py"


def compute_cache_key(
    source: str,
    child_keys: list[str],
    imports_mtimes_map: dict[str, float],
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


def write_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` without leaving a half-written file.

    Tmp file in the same directory + fsync + atomic rename. The
    per-PID suffix keeps two parallel workers from clobbering each
    other's tmp file mid-write.
    """
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def imports_mtimes(stmts: list[str]) -> dict[str, float]:
    """Resolve each `imports:` statement's top-level module to a file
    mtime so a Python-side edit invalidates downstream cache entries.

    Modules whose source can't be located (builtins, frozen, namespace
    packages, anything `importlib` can't `find_spec` for) get `0.0` —
    same value every time, so the key stays stable rather than
    chasing import-resolution noise.
    """
    out: dict[str, float] = {}
    seen: set[str] = set()
    for stmt in stmts:
        try:
            tree = ast.parse(stmt, mode="exec")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    roots = [node.module.split(".")[0]]
            for root in roots:
                if root in seen:
                    continue
                seen.add(root)
                out[root] = _module_mtime(root)
    return out


def _module_mtime(mod_name: str) -> float:
    try:
        spec = importlib.util.find_spec(mod_name)
    except (ImportError, ValueError):
        return 0.0
    if spec is None or spec.origin is None:
        return 0.0
    try:
        return os.path.getmtime(spec.origin)
    except OSError:
        return 0.0
