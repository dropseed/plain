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
from dataclasses import dataclass
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

        # Before the file is run, so that it is said even though running
        # the file would stop at the import, with pytest not installed.
        pytest_import = pytest_import_in(tree)
        if pytest_import is not None:
            raise ImportsPytest(
                imported_at=pytest_import,
                uses=pytest_names_used(tree),
                other_import_problems=problems,
                layout=self.layout,
            )

        if problems:
            raise ImportsAnotherWay(problems, layout=self.layout)

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


def _imported_from_a_conftest(node: ast.Import | ast.ImportFrom) -> str | None:
    """What an import takes from a conftest, or None if it isn't one of one."""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module.split(".")[-1] == "conftest":
            return ", ".join(f"`{alias.name}`" for alias in node.names)
        if any(alias.name == "conftest" for alias in node.names):
            return "what it holds"
    elif any(alias.name.split(".")[-1] == "conftest" for alias in node.names):
        return "what it holds"
    return None


def import_problems(tree: ast.Module, *, layout: Layout) -> list[str]:
    """
    Imports in a test module that reach a helper module some way other than
    its bare name, or that reach a conftest.

    A relative import is refused: the packages a test module is in are
    empty, so there is nothing beside it to import. An import through the
    tests directory's own name (`tests.helpers`) works only when the command
    runs from the directory above it, and loads a second copy of a module
    that something else imported as `helpers`.
    """
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        from_a_conftest = _imported_from_a_conftest(node)
        if from_a_conftest is not None:
            problems.append(
                f"line {node.lineno}: `{ast.unparse(node)}` imports from a "
                "conftest.py, which is a pytest file. Import "
                f"{from_a_conftest} from the helper module it moves to."
            )
            continue
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


# The names pytest and what comes with it are imported by. A plugin is
# `pytest_<name>`, and pytest's own insides are `_pytest`.
def is_pytest(module_name: str) -> bool:
    top = module_name.split(".")[0]
    return top == "pytest" or top.startswith(("pytest_", "_pytest"))


@dataclass(frozen=True, kw_only=True)
class PytestImport:
    line: int
    # The import as the file wrote it: `import pytest`.
    written: str


class ImportsAnotherWay(TestDefinitionError):
    """
    A test file imports a helper module some way other than by its bare
    name. Each problem says what to write, so a run that finds them in many
    files says why once.
    """

    def __init__(self, problems: list[str], *, layout: Layout) -> None:
        self.problems = problems
        helpers_file = layout.shown(layout.helper_directory / "helpers.py")
        self.why = (
            "A helper module is imported by its bare name, whichever\n"
            "directory the test file is in and wherever the command runs\n"
            f"from: {helpers_file} is `helpers`."
        )
        super().__init__(f"{self.what_is_wrong()}\n\n{self.why}")

    def what_is_wrong(self) -> str:
        listed = "\n".join(f"  {problem}" for problem in self.problems)
        return f"These imports can't be used in a test file:\n\n{listed}"


class ImportsPytest(TestDefinitionError):
    """
    A test file imports pytest. What it says on its own is the whole of it:
    where, what the file uses from pytest, and what replaces each. A run
    that finds it in many files says the last part once, from `uses`.
    """

    def __init__(
        self,
        *,
        imported_at: PytestImport,
        uses: dict[str, int],
        other_import_problems: list[str],
        layout: Layout,
        imported_by: str | None = None,
    ) -> None:
        self.imported_at = imported_at
        self.uses = uses
        self.other_import_problems = other_import_problems
        # The helper module that imports it, when it isn't the test file.
        self.imported_by = imported_by
        super().__init__(
            "\n\n".join(
                [
                    self.what_this_file_does(),
                    what_replaces_pytest(uses, layout=layout, used_by="this file"),
                ]
            ),
            line=imported_at.line if imported_by is None else None,
        )

    def what_this_file_does(self, *, explained_for: str | None = None) -> str:
        """
        Where pytest is imported, and what is used from it. `explained_for`
        is the file whose error says what replaces pytest, in a run that
        has said it already.
        """
        where = f"line {self.imported_at.line}"
        if self.imported_by is not None:
            where = f"{self.imported_by}, {where}"
        lines = [f"{where}: `{self.imported_at.written}`"]

        sentences = []
        if self.uses:
            used = ", ".join(
                f"{name} ×{count}" if count > 1 else name
                for name, count in self.uses.items()
            )
            sentences.append(f"It uses {used}.")
        if explained_for is not None:
            sentences.append(
                f"What replaces pytest is in the error for {explained_for}."
            )
        if sentences:
            lines.append(" ".join(sentences))

        lines.extend(self.other_import_problems)
        return "\n".join(lines)


_WHAT_REPLACES = {
    "pytest.raises": "`raises`, from plain.test. What was caught is\n`caught.exception`, read after the block.",
    "pytest.fixture": "a helper function the test calls in its body. One that\ncleans up after itself is a `@contextmanager` the test enters\nwith `with`. One with `autouse=True` is a TestLifecycle's\n`around_test()`, in {lifecycle_file}.",
    "pytest.mark.parametrize": "`@cases`, from plain.test: one tuple for each case.",
    "pytest.param": '`case(..., id="name")`, from plain.test.',
    "pytest.mark.skip": '`@skip("reason")`, from plain.test.',
    "pytest.mark.skipif": '`skip_test("reason")` in the test, under the `if`.',
    "pytest.mark.xfail": '`@skip("reason")`, or `raises` around what fails.',
    "pytest.mark.usefixtures": "the helper, called or entered in the test's body.",
    "pytest.skip": '`skip_test("reason")`, from plain.test.',
    "pytest.fail": '`raise AssertionError("why")`.',
    "pytest.approx": "`math.isclose(a, b, abs_tol=...)`.",
    "pytest.MonkeyPatch": '`with patch(target, "name", value):`, from plain.test.',
    "pytest.warns": "`warnings.catch_warnings(record=True)`.",
    "pytest.deprecated_call": "`warnings.catch_warnings(record=True)`.",
}

_WHAT_REPLACES_A_MARK = '`@tag("name")`, from plain.test.'

WHERE_THE_PYTEST_TABLE_IS = 'plain docs test --search "Migrating from pytest"'


def what_replaces_pytest(uses: dict[str, int], *, layout: Layout, used_by: str) -> str:
    """
    What to write instead of each thing used from pytest. `used_by` is who
    uses them: "this file", or "these files".
    """
    lifecycle_file = layout.shown(layout.helper_directory / "lifecycle.py")

    lines = ["pytest isn't used here, and isn't installed."]
    replaced = []
    for name in uses:
        replacement = _WHAT_REPLACES.get(name)
        if replacement is None and name.startswith("pytest.mark."):
            replacement = _WHAT_REPLACES_A_MARK
        if replacement is None:
            continue
        replacement = replacement.replace("{lifecycle_file}", lifecycle_file)
        first, *rest = replacement.split("\n")
        replaced.append(f"  {name}: {first}")
        replaced.extend(f"    {line}" for line in rest)
    if replaced:
        uses_them = "uses" if used_by == "this file" else "use"
        lines += ["", f"What replaces what {used_by} {uses_them}:", "", *replaced]
    lines += [
        "",
        f"Everything pytest had and what replaces it: {WHERE_THE_PYTEST_TABLE_IS}",
    ]
    return "\n".join(lines)


def pytest_import_in(tree: ast.Module) -> PytestImport | None:
    """The first import of pytest in a module, if it has one."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported = [node.module or ""]
        else:
            continue
        if any(is_pytest(name) for name in imported):
            found.append(node)
    if not found:
        return None
    first = min(found, key=lambda node: node.lineno)
    return PytestImport(line=first.lineno, written=ast.unparse(first))


def pytest_names_used(tree: ast.Module) -> dict[str, int]:
    """
    What a module uses from pytest and how many times, most used first:
    `{"pytest.raises": 4, "pytest.mark.parametrize": 2}`.
    """
    # What the module calls pytest, and what it calls the names it took
    # from it: `import pytest as pt`, `from pytest import raises as throws`.
    modules = set()
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pytest":
                    modules.add(alias.asname or alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module == "pytest"
        ):
            for alias in node.names:
                names[alias.asname or alias.name] = f"pytest.{alias.name}"

    counts: dict[str, int] = {}

    def count(node: ast.AST) -> None:
        dotted = _dotted_name(node)
        if dotted is not None:
            root, _, rest = dotted.partition(".")
            if root in modules and rest:
                used = f"pytest.{rest}"
            elif root in names:
                used = names[root] + (f".{rest}" if rest else "")
            else:
                used = None
            if used is not None:
                counts[used] = counts.get(used, 0) + 1
                # `pytest.mark.parametrize` is one use, not three.
                return
        for child in ast.iter_child_nodes(node):
            count(child)

    for statement in tree.body:
        if not isinstance(statement, ast.Import | ast.ImportFrom):
            count(statement)
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _dotted_name(node: ast.AST) -> str | None:
    """`pytest.mark.skip` for the expression that says so, or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))
