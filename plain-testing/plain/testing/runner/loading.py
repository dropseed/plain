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
import dataclasses
import functools
import hashlib
import importlib.machinery
import importlib.util
import marshal
import os
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path

from ..definition import TestDefinitionError
from . import assertions, problems
from .layout import TEST_MODULES_PACKAGE, Layout
from .problems import CantBeRunAsWritten, ProblemsInAFile, tests_as_written

__all__ = []

_CACHE_TAG_PREFIX = "plaintest"


@dataclass(frozen=True, kw_only=True)
class RewriterWork:
    """
    The test files the loader has handled in this process: how many were
    rewritten and compiled, how many were read back from the cache, and how
    long each took. A cold cache is the difference between the two.
    """

    rewritten_files: int = 0
    rewritten_seconds: float = 0.0
    cached_files: int = 0
    cached_seconds: float = 0.0

    def since(self, before: RewriterWork) -> RewriterWork:
        return RewriterWork(
            rewritten_files=self.rewritten_files - before.rewritten_files,
            rewritten_seconds=self.rewritten_seconds - before.rewritten_seconds,
            cached_files=self.cached_files - before.cached_files,
            cached_seconds=self.cached_seconds - before.cached_seconds,
        )


_work = RewriterWork()


def rewriter_work() -> RewriterWork:
    """The work done so far. Take one before and one after to count a run's."""
    return _work


# A bytecode file's header: the interpreter's magic number, a flags field
# (zero for a file checked against its source's time and size), then the
# time and the size, four bytes each.
_NO_FLAGS = (0).to_bytes(4, "little")
_HEADER_LENGTH = 16


def load_test_module(path: Path, *, layout: Layout) -> types.ModuleType:
    """The module for one test file, loaded if it hasn't been."""
    name = _module_name_for(path, layout=layout)
    loaded = sys.modules.get(name)
    # The name says where a file is under the root, so two roots have files
    # of the same name. Only the same file is the same module.
    if loaded is not None and getattr(loaded, "__file__", None) == str(path):
        return loaded

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
    except ModuleNotFoundError as error:
        sys.modules.pop(name, None)
        problems = imports_of_a_helper_by_part_of_its_path(
            path, missing=error.name, layout=layout
        )
        if problems:
            raise ImportsAnotherWay(problems, layout=layout) from error
        raise
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _module_name_for(path: Path, *, layout: Layout) -> str:
    if path.is_relative_to(layout.root):
        relative = path.relative_to(layout.root)
        return ".".join([TEST_MODULES_PACKAGE, *relative.with_suffix("").parts])
    return f"{TEST_MODULES_PACKAGE}.{path.stem}"


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

        # A file that can't be run says everything reading it shows, about
        # its imports and about its tests. Run, it would stop at the first
        # of them, and each would take a run of its own to find.
        imports = import_problems(tree, layout=self.layout, path=Path(path))
        tests = tests_as_written(tree)

        if imports:
            raise ImportsAnotherWay(imports, tests=tests, layout=self.layout)

        if tests.stops_at_a_decorator:
            raise CantBeRunAsWritten(tests)

        # Anything else wrong with its tests is found by running it and
        # looking at them, which sees more than reading does.

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
        global _work

        started = time.perf_counter()
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
                        code = marshal.loads(cached[_HEADER_LENGTH:])
                    except EOFError, ValueError, TypeError:
                        pass  # cut short or damaged: compile it again
                    else:
                        _work = dataclasses.replace(
                            _work,
                            cached_files=_work.cached_files + 1,
                            cached_seconds=_work.cached_seconds
                            + (time.perf_counter() - started),
                        )
                        return code

        code = self.source_to_code(self.get_data(source_path), source_path)

        if self.cache_path is not None and not sys.dont_write_bytecode:
            # Makes the directory, writes the file in one step, and lets a
            # directory that can't be written to pass without a word, as it
            # does for any module's bytecode.
            self.set_data(self.cache_path, header + marshal.dumps(code))
            _remove_caches_left_by_other_rewriters(Path(self.cache_path))
        _work = dataclasses.replace(
            _work,
            rewritten_files=_work.rewritten_files + 1,
            rewritten_seconds=_work.rewritten_seconds + (time.perf_counter() - started),
        )
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
    for module in (assertions, problems, sys.modules[__name__]):
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


def import_problems(tree: ast.Module, *, layout: Layout, path: Path) -> list[str]:
    """
    Imports in the test module at `path` that reach a helper module some way
    other than by its path from the tests directory.

    A relative import is refused: the packages a test module is in are
    empty, so there is nothing beside it to import. An import through the
    tests directory's own name (`tests.helpers`) works only when the command
    runs from the directory above it, and loads a second copy of a module
    that something else imported as `helpers`.
    """
    directories = _directories_a_file_is_under(path, layout=layout)

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
                # One dot is the file's own directory, and each dot more is
                # a directory further up.
                up = node.level - 1
                beside = directories[: len(directories) - up] if up else directories
                if up > len(directories):
                    beside = ()
                from_module = ".".join([*beside, *([module] if module else [])])
            elif module.split(".")[0] == layout.refused_import_name:
                written = f"from {module} import {names}"
                from_module = module.partition(".")[2]
            else:
                continue
            if from_module:
                corrected = f"from {from_module} import {names}"
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


def _directories_a_file_is_under(path: Path, *, layout: Layout) -> tuple[str, ...]:
    """
    The directories between the tests directory and a file in it:
    `("billing", "refunds")` for `tests/billing/refunds/test_partial.py`,
    and none for a file in the tests directory itself.
    """
    directory = path.parent
    if directory.is_relative_to(layout.helper_directory):
        return directory.relative_to(layout.helper_directory).parts
    return ()


def imports_of_a_helper_by_part_of_its_path(
    path: Path, *, missing: str | None, layout: Layout
) -> list[str]:
    """
    What to write, when the test file at `path` couldn't import `missing`
    and a module by that name is further down in the tests directory.

    `tests/billing/helpers.py` is `billing.helpers`. A test file beside it
    that writes `from helpers import charge` finds nothing, or finds
    `tests/helpers.py`, which is another module. Only the first can be told
    from here, and it is told when it happens: what is in the tests
    directory can change without the test file changing.
    """
    if not missing:
        return []
    top_name = missing.split(".")[0]

    where_it_is = []
    for directory, directory_names, file_names in os.walk(layout.helper_directory):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not name.startswith(".") and name != "__pycache__"
        )
        if Path(directory) == layout.helper_directory:
            continue
        if f"{top_name}.py" in file_names or top_name in directory_names:
            under = Path(directory).relative_to(layout.helper_directory).parts
            where_it_is.append(".".join(under))
    if not where_it_is:
        return []

    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except OSError, SyntaxError, ValueError:
        return []

    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.split(".")[0] != top_name:
                continue
            names = ", ".join(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
                for alias in node.names
            )
            written = f"from {module} import {names}"
            corrected = [
                f"from {under}.{module} import {names}" for under in where_it_is
            ]
        elif isinstance(node, ast.Import):
            by_that_name = [
                alias for alias in node.names if alias.name.split(".")[0] == top_name
            ]
            if not by_that_name:
                continue
            alias = by_that_name[0]
            written = f"import {alias.name}"
            if alias.asname:
                written += f" as {alias.asname}"
            corrected = [
                f"import {under}.{alias.name} as {alias.asname or top_name}"
                for under in where_it_is
            ]
        else:
            continue
        either = " or ".join(f"`{one}`" for one in corrected)
        problems.append(f"line {node.lineno}: `{written}` should be {either}")
    return problems


class ImportsAnotherWay(TestDefinitionError):
    """
    A test file imports a helper module some way other than by its path
    from the tests directory. Each problem says what to write, so a run that
    finds them in many files says why once.
    """

    def __init__(
        self,
        problems: list[str],
        *,
        layout: Layout,
        tests: ProblemsInAFile | None = None,
    ) -> None:
        self.problems = problems
        # What reading the file showed about its tests.
        self.tests = tests or ProblemsInAFile()
        at_the_top = layout.shown(layout.helper_directory / "helpers.py")
        further_down = layout.shown(layout.helper_directory / "billing" / "helpers.py")
        self.why = (
            "A helper module is imported by its path from the tests directory,\n"
            "whichever directory the test file is in and wherever the command\n"
            f"runs from: {at_the_top} is `helpers`, and\n"
            f"{further_down} is `billing.helpers`."
        )
        super().__init__(f"{self.what_is_wrong()}\n\n{self.why}")

    def what_is_wrong(self) -> str:
        listed = "\n".join(f"  {problem}" for problem in self.problems)
        return f"These imports can't be used in a test file:\n\n{listed}"
