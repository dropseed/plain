"""
Loading a test module.

A test module is loaded by Python's import machinery, through a loader that
differs from the ordinary one in one step. `source_to_code` is where a file's
source becomes a code object, and here it checks the file's imports and
rewrites its asserts on the way. Everything else is the standard library's:
the module has a spec, a loader, a file and a cache, so `inspect`, `pickle`,
tracebacks and debuggers treat it as they treat any module.

The runner builds the spec for each file it has already decided is a test
file. Nothing is installed on `sys.meta_path`: there is no import to
intercept, because nothing imports a test module by name.

The rewritten bytecode is cached beside the ordinary cache, under a name an
ordinary import never looks for. See `cache_path_for`.
"""

import ast
import functools
import hashlib
import importlib.machinery
import importlib.util
import marshal
import sys
import types
from pathlib import Path

from ..definition import TestDefinitionError
from . import assertions
from .layout import Layout

__all__ = []

# Test modules are named for where they are, under this name, so two files
# called `test_views.py` in different directories are different modules.
_TOP_PACKAGE_NAME = "plain_tests"

_CACHE_TAG_PREFIX = "plaintest"

# A bytecode file's header: the interpreter's magic number, a flags field
# (zero for a file checked against its source's time and size), then the
# time and the size, four bytes each.
_NO_FLAGS = (0).to_bytes(4, "little")
_HEADER_LENGTH = 16


def load_test_module(path: Path, *, layout: Layout) -> types.ModuleType:
    """The module for one test file, loaded if it hasn't been."""
    name = _module_name_for(path, layout=layout)
    if name in sys.modules:
        return sys.modules[name]

    loader = TestModuleLoader(name, str(path), layout=layout)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    assert spec is not None
    # Where this module's bytecode really is, not where an ordinary import
    # of the same file would have put it.
    spec.cached = loader.cache_path
    module = importlib.util.module_from_spec(spec)

    _add_to_its_packages(module)
    sys.modules[name] = module
    try:
        loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _module_name_for(path: Path, *, layout: Layout) -> str:
    if path.is_relative_to(layout.root):
        relative = path.relative_to(layout.root)
        return ".".join([_TOP_PACKAGE_NAME, *relative.with_suffix("").parts])
    return f"{_TOP_PACKAGE_NAME}.{path.stem}"


def _add_to_its_packages(module: types.ModuleType) -> None:
    """
    Make the packages a test module's name says it is in, and put each one
    in the one above it.

    `plain_tests.public.test_views` names two packages that exist nowhere
    on disk. Anything that finds a module by its name imports the packages
    first (unpickling an instance of a class the test file defines is one),
    so they have to be there. They are empty: a package with no search
    path, which nothing can be imported from.
    """
    child = module
    name = module.__name__
    while "." in name:
        name, _, child_name = name.rpartition(".")
        package = sys.modules.get(name)
        if package is None:
            package = importlib.util.module_from_spec(
                importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
            )
            sys.modules[name] = package
        setattr(package, child_name, child)
        child = package


class TestModuleLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname: str, path: str, *, layout: Layout) -> None:
        super().__init__(fullname, path)
        self.layout = layout
        self.cache_path = cache_path_for(
            path, refused_import_name=layout.refused_import_name
        )

    def source_to_code(self, data: bytes, path: str) -> types.CodeType:  # ty: ignore[invalid-method-override]
        source = importlib.util.decode_source(data)
        tree = ast.parse(source, filename=path)

        problems = import_problems(tree, layout=self.layout)
        if problems:
            listed = "\n".join(f"  {problem}" for problem in problems)
            helpers_file = self.layout.shown(
                self.layout.helper_directory / "helpers.py"
            )
            raise TestDefinitionError(
                f"These imports can't be used in a test file:\n\n{listed}\n\n"
                "A helper module is imported by its bare name, whichever\n"
                "directory the test file is in and wherever the command runs\n"
                f"from: {helpers_file} is `helpers`."
            )

        tree = assertions.rewrite_asserts(tree, source=source)
        # dont_inherit: a test module is compiled with its own __future__
        # statements and nothing else. Without it, compile() would also apply
        # whatever compiler flags are in effect in this file — none today,
        # but a test module's semantics shouldn't depend on that staying true.
        return compile(tree, path, "exec", dont_inherit=True)

    def get_code(self, fullname: str) -> types.CodeType:
        """
        The module's code: from the cache when the cache was written from
        the source as it is now, and from the source otherwise.

        This is what the standard loader's `get_code` does, with the cache
        in a different place. It can't be told where to look, so the steps
        are written out here.
        """
        source_path = self.get_filename(fullname)
        stats = self.path_stats(source_path)
        # A bytecode file has four bytes for each, as the standard one does.
        source_time = int(stats["mtime"]) & 0xFFFFFFFF
        source_size = stats["size"] & 0xFFFFFFFF
        header = (
            importlib.util.MAGIC_NUMBER
            + _NO_FLAGS
            + source_time.to_bytes(4, "little")
            + source_size.to_bytes(4, "little")
        )

        if self.cache_path is not None:
            try:
                cached = self.get_data(self.cache_path)
            except OSError:
                pass  # nothing cached yet
            else:
                if cached[:_HEADER_LENGTH] == header:
                    try:
                        return marshal.loads(cached[_HEADER_LENGTH:])
                    except EOFError, ValueError, TypeError:
                        pass  # cut short or damaged: compile it again

        code = self.source_to_code(self.get_data(source_path), source_path)

        if self.cache_path is not None and not sys.dont_write_bytecode:
            # Makes the directory, writes the file in one step, and lets a
            # directory that can't be written to pass without a word, as it
            # does for any module's bytecode.
            self.set_data(self.cache_path, header + marshal.dumps(code))
            _remove_caches_left_by_other_rewriters(Path(self.cache_path))
        return code


def cache_path_for(source_path: str, *, refused_import_name: str | None) -> str | None:
    """
    Where a test file's rewritten bytecode is kept, or None if this
    interpreter keeps no bytecode.

    It goes where Python would put the file's bytecode (`__pycache__`, or
    under `PYTHONPYCACHEPREFIX`), with a tag of its own in the name, in the
    place Python puts `opt-1` and `opt-2`:

        __pycache__/test_views.cpython-314.opt-plaintest3f2a9c1b7d04.pyc

    An ordinary import of the file reads `test_views.cpython-314.pyc`, so it
    never gets bytecode with rewritten asserts in it.

    The tag changes when the rewriter does. What a cached file holds depends
    on the source, which its header is checked against, and on the code that
    rewrote it, which the tag stands for.
    """
    tag = _CACHE_TAG_PREFIX + _what_rewrites(refused_import_name=refused_import_name)
    try:
        return importlib.util.cache_from_source(source_path, optimization=tag)
    except NotImplementedError:
        return None


@functools.cache
def _what_rewrites(*, refused_import_name: str | None) -> str:
    """
    Twelve characters that change whenever a test module would be compiled
    differently from the same source: when the rewriter changes, when this
    module changes, and when a different import would be refused.

    The last matters because a file is only cached once its imports have
    passed the check, and what the check refuses depends on the layout.
    """
    digest = hashlib.sha256()
    for module in (assertions, sys.modules[__name__]):
        assert module.__file__ is not None
        digest.update(Path(module.__file__).read_bytes())
    digest.update(repr(refused_import_name).encode())
    return digest.hexdigest()[:12]


def _remove_caches_left_by_other_rewriters(cache_path: Path) -> None:
    """
    Remove what earlier versions of the rewriter cached for the same file.
    Each one has a tag nothing will ask for again.
    """
    # test_views.cpython-314.opt-plaintest3f2a9c1b7d04.pyc
    #   -> test_views.cpython-314.opt-plaintest
    until_the_tag, _, _ = cache_path.name.rpartition(_CACHE_TAG_PREFIX)
    for other in cache_path.parent.glob(f"{until_the_tag}{_CACHE_TAG_PREFIX}*.pyc"):
        if other != cache_path:
            other.unlink(missing_ok=True)


def import_problems(tree: ast.Module, *, layout: Layout) -> list[str]:
    """
    Imports in a test module that reach a helper module some way other than
    its bare name.

    A relative import is refused: the packages a test module is in are
    empty, so there is nothing beside it to import. An import through the
    tests directory's own name (`tests.helpers`) works only when the command
    runs from the directory above it, and loads a second copy of a module
    that something else imported as `helpers`.
    """
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in node.names
            )
            if node.level > 0:
                written = f"from {'.' * node.level}{module} import {names}"
                bare_module = module
            elif module.split(".")[0] == layout.refused_import_name:
                written = f"from {module} import {names}"
                bare_module = module.partition(".")[2]
            else:
                continue
            if bare_module:
                corrected = f"from {bare_module} import {names}"
            else:
                corrected = f"import {names}"
        elif isinstance(node, ast.Import):
            through = [
                alias.name
                for alias in node.names
                if "." in alias.name
                and alias.name.split(".")[0] == layout.refused_import_name
            ]
            if not through:
                continue
            written = f"import {through[0]}"
            corrected = f"import {through[0].partition('.')[2]}"
        else:
            continue
        problems.append(f"line {node.lineno}: `{written}` should be `{corrected}`")
    return problems
