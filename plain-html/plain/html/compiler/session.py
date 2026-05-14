"""Compile-session walking the `:include` graph.

A `CompileSession` walks depth-first: a parent is compiled only after
every leaf it depends on has its own compiled module ready. Each
compiled `render` is injected into the parent's module globals as
`_inc_0`, `_inc_1`, … before the parent module is exec'd.

Cycle detection is instance-local (`_in_progress`); the already-
compiled cache is process-wide so dynamic includes at render time
reuse work from startup. The disk cache (`.._cache`) is opt-in per
session.
"""

from __future__ import annotations

import threading
import types
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .. import _cache
from .. import frontmatter as fm
from ..loader import find_template
from ..parser import ElementNode, Node, parse
from ..tokenizer import tokenize
from . import CompileError
from .emit import emit_module

# Resolver signature: (name, *, current_template) -> resolved Path.
# Matches `loader.find_template` so it can be used as the default.
PathResolver = Callable[..., Path]


# --- process cache ----------------------------------------------------------


@dataclass
class _CompiledEntry:
    """One process-cache slot: the callable + the cache key that
    produced it. The key is what a parent uses to compute its own key
    (so an edit anywhere in the include graph invalidates upward).
    """

    render: Callable[..., str]
    key: str


# Process-wide compiled-template cache. Shared across CompileSessions so a
# template reached via the dynamic `:include={expr}` resolver at render time
# can hit a module that was already compiled by a startup pass. The lock is
# coarse — under contention multiple threads may compile the same template
# concurrently; whoever finishes first wins the cache slot, the others' work
# is discarded. Acceptable: compile output is deterministic, the loss is
# only the extra compile cycles.
#
# An `OrderedDict` backs the cache so we can evict the least-recently-used
# entry once the size exceeds `_PROCESS_CACHE_MAX`. The cap matters for
# long-running test runners or scripts that compile many ad-hoc templates;
# normal projects sit well below the limit.
_PROCESS_CACHE_MAX = 512
_PROCESS_CACHE: OrderedDict[Path, _CompiledEntry] = OrderedDict()
_PROCESS_LOCK = threading.Lock()


def _process_cache_get(path: Path) -> _CompiledEntry | None:
    with _PROCESS_LOCK:
        entry = _PROCESS_CACHE.get(path)
        if entry is not None:
            _PROCESS_CACHE.move_to_end(path)
        return entry


def _process_cache_set(path: Path, entry: _CompiledEntry) -> None:
    with _PROCESS_LOCK:
        _PROCESS_CACHE[path] = entry
        _PROCESS_CACHE.move_to_end(path)
        while len(_PROCESS_CACHE) > _PROCESS_CACHE_MAX:
            _PROCESS_CACHE.popitem(last=False)


def clear_process_cache() -> None:
    """Empty the process-wide compiled-template cache.

    Mostly useful in tests; production callers don't need this — disk
    cache invalidation happens via cache-key changes, not by clearing.
    """
    with _PROCESS_LOCK:
        _PROCESS_CACHE.clear()


def get_or_compile(path: Path) -> Callable[..., str]:
    """Return a compiled `render` for `path`, hitting the process cache
    if available. Used by the dynamic `:include={expr}` resolver so
    runtime-resolved targets share cache with startup-compiled ones.

    Defaults to disk caching ON — at render time we want compile cost
    paid only once across processes, not on every cold start.
    """
    path = path.resolve()
    cached = _process_cache_get(path)
    if cached is not None:
        return cached.render
    return CompileSession(use_disk_cache=True).compile_path(path)


# --- CompileSession ---------------------------------------------------------


class CompileSession:
    """One compile pass over the `:include` graph.

    Walks depth-first: a parent is compiled only after every leaf it
    depends on has its own compiled module ready. Each compiled
    `render` is injected into the parent's module globals as `_inc_0`,
    `_inc_1`, … before the parent module is exec'd.

    Cycle detection is instance-local (`_in_progress`); the
    already-compiled cache is process-wide so dynamic includes at
    render time reuse work from startup.
    """

    def __init__(
        self,
        *,
        resolver: PathResolver | None = None,
        use_disk_cache: bool = False,
    ) -> None:
        self.resolver: PathResolver = resolver or find_template
        self.use_disk_cache = use_disk_cache
        self._in_progress: set[Path] = set()

    def compile_string(self, source: str, *, label: str = "<source>") -> str:
        """Tokenize + parse + emit Python source for a standalone template.

        Returns the generated module source as a string — the caller is
        responsible for compiling/exec'ing it. Use this when there's no
        backing file (in-memory templates, tests, the bench). Templates
        with a literal `:include` raise `CompileError` at emit time since
        there's no `:include` graph for the session to walk.
        """
        fmdict, body = fm.split(source)
        tokens = tokenize(body)
        tree = parse(tokens)
        return emit_module(tree, fmdict, label, include_renders={})

    def compile_path(
        self,
        path: Path,
        *,
        source_override: str | None = None,
    ) -> Callable[..., str]:
        """Compile the template at `path`. Returns its `render` callable.

        Pass `source_override` when the caller has the template source
        in memory and just wants includes resolved relative to the
        given path (e.g. `plain.pages` rendering Markdown-prefixed
        templates). Process-cache hits ignore source_override — they
        assume the path's content is stable.
        """
        path = path.resolve()
        cached = _process_cache_get(path)
        if cached is not None:
            return cached.render
        if path in self._in_progress:
            raise CompileError(f"`:include` cycle detected involving {path}")
        self._in_progress.add(path)
        try:
            entry = self._compile_one(path, source_override=source_override)
        finally:
            self._in_progress.discard(path)
        _process_cache_set(path, entry)
        return entry.render

    def _compile_one(
        self, path: Path, *, source_override: str | None = None
    ) -> _CompiledEntry:
        source = (
            source_override
            if source_override is not None
            else path.read_text(encoding="utf-8")
        )
        fmdict, body = fm.split(source)
        tokens = tokenize(body)
        tree = parse(tokens)

        # Walk the tree, find every literal `:include`, recursively compile its
        # target, and assign each include site a unique `_inc_N` slot. Dynamic
        # `:include={expr}` sites stay unresolved here — they're handled by a
        # runtime helper that looks up + compiles on demand.
        include_renders: dict[int, str] = {}
        include_funcs: dict[str, Callable[..., str]] = {}
        child_keys: list[str] = []
        idx = 0
        for inc_node in _walk_includes(tree):
            if inc_node.include_path_code is not None:
                # Dynamic include — resolver runs at render time. Doesn't
                # contribute to this template's cache key, since the target
                # is unknowable at compile time.
                continue
            assert inc_node.include_path is not None
            child_path = self.resolver(inc_node.include_path, current_template=path)
            child_render = self.compile_path(child_path)
            slot_name = f"_inc_{idx}"
            include_renders[id(inc_node)] = slot_name
            include_funcs[slot_name] = child_render
            idx += 1
            # The child's entry has a key — pick it up so this template's key
            # transitively reflects child changes.
            child_entry = _process_cache_get(child_path.resolve())
            if child_entry is not None:
                child_keys.append(child_entry.key)

        imports = list(fmdict.get("imports") or [])
        mtimes = _cache.imports_mtimes(imports) if self.use_disk_cache else {}
        key = _cache.compute_cache_key(source, child_keys, mtimes)

        cached_file = _cache.cache_file_for(key, path) if self.use_disk_cache else None

        if cached_file is not None and cached_file.exists():
            # Disk-cache hit: skip codegen, exec the cached `.py` with the
            # same `_inc_N` injection a fresh compile would have done.
            src = cached_file.read_text(encoding="utf-8")
        else:
            src = emit_module(tree, fmdict, str(path), include_renders=include_renders)
            if cached_file is not None:
                _cache.write_atomic(cached_file, src)

        mod = types.ModuleType(f"_plain_html_compiled_{abs(hash(str(path)))}")
        mod.__file__ = str(path)
        # Inject child renderers as module globals before exec so the
        # generated bare-name references resolve.
        mod.__dict__.update(include_funcs)
        code = compile(src, str(path), "exec")
        exec(code, mod.__dict__)
        return _CompiledEntry(render=mod.render, key=key)


def _walk_includes(nodes: list[Node]) -> Iterator[ElementNode]:
    """Yield every ElementNode that has `:include` set, in tree order."""
    for node in nodes:
        if isinstance(node, ElementNode):
            if node.include_path is not None or node.include_path_code is not None:
                yield node
            yield from _walk_includes(node.children)
