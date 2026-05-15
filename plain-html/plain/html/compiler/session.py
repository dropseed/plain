"""Compile-session walking the component graph.

A `CompileSession` walks depth-first: a parent is compiled only after
every leaf it depends on has its own compiled module ready. Each
compiled `render` is injected into the parent's module globals as
`_inc_0`, `_inc_1`, … before the parent module is exec'd.

Cycle detection is instance-local (`_in_progress`); the already-
compiled cache is process-wide so a component reached again from a
later compile reuses work from startup. The disk cache (`.._cache`)
is opt-in per session.

Source-mapped tracebacks: after emitting the generated source, this
module parses it to AST, walks every node, and rewrites `lineno` /
`end_lineno` to point at the template body offset that produced each
generated line (via `emit_module`'s `line_offsets` table). The
resulting code object has `co_filename = <template path>`, so a
template `KeyError` shows up as `File "templates/x.html", line N` in
the traceback — `linecache` then reads the .html for the source line.
"""

from __future__ import annotations

import ast
import marshal
import threading
import types
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import CodeType

from .. import _cache
from .. import frontmatter as fm
from ..components import parse_components
from ..loader import find_template
from ..parser import ElementNode, ForNode, IfNode, Node, SlotNode, parse
from ..positions import body_offset, offset_to_line_col
from ..tokenizer import tokenize
from . import CompileError
from .emit import EmittedModule, emit_module

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
# template reached again from a later compile pass can hit a module that
# was already compiled by an earlier pass. The lock is coarse — under
# contention multiple threads may compile the same template concurrently;
# whoever finishes first wins the cache slot, the others' work is
# discarded. Acceptable: compile output is deterministic, the loss is
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
    if available. The entry point `engine.render` uses this so repeated
    renders of the same template skip compile cost.

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
    """One compile pass over the component graph.

    Walks depth-first: a parent is compiled only after every leaf it
    depends on has its own compiled module ready. Each compiled
    `render` is injected into the parent's module globals as `_inc_0`,
    `_inc_1`, … before the parent module is exec'd.

    Cycle detection is instance-local (`_in_progress`); the
    already-compiled cache is process-wide so a component reached
    again from a later compile pass reuses earlier work.
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
        invoking a component tag raise `CompileError` at emit time since
        there's no component graph for the session to walk.

        Note: in-memory compiles via this entry point don't get source
        mapping (no template path → nothing for `linecache` to read).
        """
        fmdict, body = fm.split(source)
        tokens = tokenize(body)
        tree = parse(tokens, components=parse_components(fmdict.get("components")))
        emitted = emit_module(tree, fmdict, label, include_renders={})
        return emitted.source

    def compile_path(
        self,
        path: Path,
        *,
        source_override: str | None = None,
    ) -> Callable[..., str]:
        """Compile the template at `path`. Returns its `render` callable.

        Pass `source_override` when the caller has the template source
        in memory and just wants component tags resolved relative to the
        given path (e.g. `plain.pages` rendering Markdown-prefixed
        templates). Process-cache hits ignore source_override — they
        assume the path's content is stable.
        """
        path = path.resolve()
        cached = _process_cache_get(path)
        if cached is not None:
            return cached.render
        if path in self._in_progress:
            raise CompileError(f"component cycle detected involving {path}")
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
        tree = parse(tokens, components=parse_components(fmdict.get("components")))

        # Walk the tree, find every component-tag site, recursively compile
        # its target, and assign each one a unique `_inc_N` slot.
        include_renders: dict[int, str] = {}
        include_funcs: dict[str, Callable[..., str]] = {}
        child_keys: list[str] = []
        idx = 0
        for inc_node in _walk_includes(tree):
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

        code: CodeType | None = None
        if cached_file is not None and cached_file.exists():
            # Disk-cache hit: load the marshalled bytecode directly. The
            # cached object already carries `co_filename = str(path)` and
            # template-mapped line numbers from when it was first compiled,
            # so source mapping survives across processes.
            try:
                code = _load_cached_code(cached_file)
            except Exception:
                # Corrupt or version-skewed cache — fall through to recompile.
                code = None

        if code is None:
            emitted = emit_module(
                tree, fmdict, str(path), include_renders=include_renders
            )
            code = _compile_with_source_map(emitted, source, str(path))
            if cached_file is not None:
                _cache.write_atomic_bytes(cached_file, marshal.dumps(code))

        mod = types.ModuleType(f"_plain_html_compiled_{abs(hash(str(path)))}")
        mod.__file__ = str(path)
        # Inject child renderers as module globals before exec so the
        # generated bare-name references resolve.
        mod.__dict__.update(include_funcs)
        exec(code, mod.__dict__)
        return _CompiledEntry(render=mod.render, key=key)


def _compile_with_source_map(
    emitted: EmittedModule,
    source: str,
    filename: str,
) -> CodeType:
    """Parse the emitted source, remap line numbers to template lines, compile.

    Generated Python lines that came from a template node carry the node's
    body offset in `emitted.line_offsets`. We convert each offset to a
    1-based line in the original `.html` file (accounting for frontmatter)
    and stamp that line onto every AST node sitting on the corresponding
    generated line. Lines without a mapping (boilerplate setup, headers)
    fall back to line 1.
    """
    tree = ast.parse(emitted.source, filename=filename, mode="exec")

    # Precompute generated_line → template_line. emit_module guarantees
    # `line_offsets` length matches the number of generated lines (1-indexed
    # gen line K is at list index K-1).
    body_off = body_offset(source)
    gen_to_tpl: dict[int, int] = {}
    for i, body_offset_val in enumerate(emitted.line_offsets):
        gen_line = i + 1
        if body_offset_val > 0:
            tpl_line, _ = offset_to_line_col(source, body_offset_val + body_off)
            gen_to_tpl[gen_line] = tpl_line

    # Walk every AST node; remap `lineno` / `end_lineno` per the table.
    # Unmapped nodes pin to line 1 — better than misattributing them to a
    # line they don't correspond to.
    for node in ast.walk(tree):
        for attr in ("lineno", "end_lineno"):
            val = getattr(node, attr, None)
            if val is None:
                continue
            mapped = gen_to_tpl.get(val)
            setattr(node, attr, mapped if mapped is not None else 1)
        # Column info from the generated source doesn't correspond to any
        # template column either — zero it so Python's enhanced tracebacks
        # don't underline a position that doesn't exist in the .html.
        for attr in ("col_offset", "end_col_offset"):
            if hasattr(node, attr):
                setattr(node, attr, 0)

    return compile(tree, filename, "exec")


def _load_cached_code(path: Path) -> CodeType:
    """Read a marshalled code object back from disk.

    The cache key (which gates the on-disk file) already includes
    `COMPILER_VERSION`, so any layout change in the codegen invalidates
    every cached entry. We still wrap `marshal.loads` defensively — a
    file from a different Python version is just garbage to us.
    """
    with open(path, "rb") as f:
        obj = marshal.load(f)
    if not isinstance(obj, CodeType):
        raise CompileError(f"cached object is not a code object: {path}")
    return obj


def _walk_includes(nodes: list[Node]) -> Iterator[ElementNode]:
    """Yield every component-tag ElementNode (`include_path` set), in tree order.

    Descends into `{% if %}` / `{% for %}` / `{% slot %}` blocks so a
    component tag nested inside control flow is still found.
    """
    for node in nodes:
        if isinstance(node, ElementNode):
            if node.include_path is not None:
                yield node
            yield from _walk_includes(node.children)
        elif isinstance(node, IfNode):
            for branch in node.branches:
                yield from _walk_includes(branch.children)
        elif isinstance(node, ForNode | SlotNode):
            yield from _walk_includes(node.children)
