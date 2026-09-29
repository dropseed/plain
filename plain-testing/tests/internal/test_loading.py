"""A test module is loaded by the import machinery, and cached out of the way.

Each test writes its files under names no other test uses, so that what one
test cached or loaded is never what another finds.
"""

import importlib
import importlib.util
import inspect
import os
import pickle
import sys
import tempfile
from pathlib import Path

from plain.testing import patch
from plain.testing.runner import loading
from plain.testing.runner.layout import Layout


def write_files(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp()).resolve()
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def layout_for(root: Path) -> Layout:
    return Layout(root=root, helper_directory=root, refused_import_name=None)


def load_again(path: Path, *, layout: Layout):
    """Load a file the way a new run would: nothing of it in `sys.modules`."""
    sys.modules.pop(loading._module_name_for(path, layout=layout), None)
    return loading.load_test_module(path, layout=layout)


def count_compiles(counted: list[str]):
    """Patch the loader so every file it compiles from source is counted."""
    compile_from_source = loading.TestModuleLoader.source_to_code

    def counting(self, data, path):
        counted.append(path)
        return compile_from_source(self, data, path)

    return patch(loading.TestModuleLoader, "source_to_code", counting)


def test_a_test_module_has_what_any_module_has():
    root = write_files({"test_loaded_whole.py": "def test_one():\n    assert 1 == 1\n"})
    path = root / "test_loaded_whole.py"

    module = loading.load_test_module(path, layout=layout_for(root))

    assert module.__name__ == "plain_tests.test_loaded_whole"
    assert module.__file__ == str(path)
    assert isinstance(module.__loader__, loading.TestModuleLoader)
    assert module.__spec__ is not None
    assert module.__spec__.origin == str(path)
    assert importlib.import_module("plain_tests.test_loaded_whole") is module
    # The source is the file's own, not the rewritten tree's.
    assert inspect.getsource(module.test_one) == (
        "def test_one():\n    assert 1 == 1\n"
    )


def test_an_instance_of_a_class_in_a_test_module_can_be_pickled():
    root = write_files(
        {
            "nested/test_pickled.py": (
                "class Order:\n"
                "    def __init__(self, total):\n"
                "        self.total = total\n"
            )
        }
    )
    module = loading.load_test_module(
        root / "nested" / "test_pickled.py", layout=layout_for(root)
    )

    copy = pickle.loads(pickle.dumps(module.Order(12)))

    assert type(copy) is module.Order
    assert copy.total == 12


def test_two_files_with_one_name_are_two_modules():
    root = write_files(
        {
            "first/test_same_name.py": "WHICH = 'first'\n",
            "second/test_same_name.py": "WHICH = 'second'\n",
        }
    )
    layout = layout_for(root)

    first = loading.load_test_module(root / "first/test_same_name.py", layout=layout)
    second = loading.load_test_module(root / "second/test_same_name.py", layout=layout)

    assert (first.WHICH, second.WHICH) == ("first", "second")


def test_the_bytecode_is_cached_where_an_ordinary_import_never_looks():
    root = write_files({"test_cached_apart.py": "assert 1 == 1\n"})
    path = root / "test_cached_apart.py"

    module = loading.load_test_module(path, layout=layout_for(root))

    assert module.__spec__ is not None
    cached = module.__spec__.cached
    assert cached is not None
    assert Path(cached).is_file()
    assert Path(cached).name.startswith(
        f"test_cached_apart.{sys.implementation.cache_tag}.opt-plaintest"
    )
    assert not Path(importlib.util.cache_from_source(str(path))).exists()


def test_a_file_that_has_not_changed_is_not_compiled_again():
    root = write_files({"test_compiled_once.py": "VALUE = 1\nassert VALUE == 1\n"})
    path = root / "test_compiled_once.py"
    layout = layout_for(root)
    compiled: list[str] = []

    with count_compiles(compiled):
        load_again(path, layout=layout)
        module = load_again(path, layout=layout)

    assert compiled == [str(path)]
    assert module.VALUE == 1


def test_a_file_that_has_changed_is_compiled_again():
    root = write_files({"test_changed_source.py": "VALUE = 1\n"})
    path = root / "test_changed_source.py"
    layout = layout_for(root)
    compiled: list[str] = []

    with count_compiles(compiled):
        load_again(path, layout=layout)
        path.write_text("VALUE = 'changed'\n")
        module = load_again(path, layout=layout)

    assert compiled == [str(path), str(path)]
    assert module.VALUE == "changed"


def test_a_file_changed_within_the_same_second_is_compiled_again():
    # The cache is checked against the source's time in whole seconds and
    # its size, so a change that keeps the time has to change the size.
    root = write_files({"test_changed_quickly.py": "VALUE = 1\n"})
    path = root / "test_changed_quickly.py"
    layout = layout_for(root)
    written_at = path.stat().st_mtime

    load_again(path, layout=layout)
    path.write_text("VALUE = 22\n")
    os.utime(path, (written_at, written_at))

    assert load_again(path, layout=layout).VALUE == 22


def test_a_change_to_the_rewriter_compiles_every_file_again():
    root = write_files({"test_rewriter_changed.py": "VALUE = 1\n"})
    path = root / "test_rewriter_changed.py"
    layout = layout_for(root)
    compiled: list[str] = []

    def another_rewriter(*, refused_import_name):
        return "0123456789ab"

    with count_compiles(compiled):
        first = load_again(path, layout=layout)
        with patch(loading, "_what_rewrites", another_rewriter):
            second = load_again(path, layout=layout)

    assert compiled == [str(path), str(path)]
    assert first.__spec__ is not None
    assert second.__spec__ is not None
    assert second.__spec__.cached.endswith(".opt-plaintest0123456789ab.pyc")
    # What the first rewriter cached is no use to anything now.
    assert not Path(first.__spec__.cached).exists()
    assert Path(second.__spec__.cached).exists()


def test_a_different_refused_import_is_a_different_cache():
    # A file is cached once its imports have passed the check, and what the
    # check refuses depends on the layout.
    apart = loading.cache_path_for("/project/tests/test_x.py", refused_import_name=None)
    inside = loading.cache_path_for(
        "/project/tests/test_x.py", refused_import_name="tests"
    )
    assert apart != inside


def test_a_damaged_cache_is_compiled_again():
    root = write_files({"test_damaged_cache.py": "VALUE = 1\n"})
    path = root / "test_damaged_cache.py"
    layout = layout_for(root)

    module = load_again(path, layout=layout)
    assert module.__spec__ is not None
    cached = Path(module.__spec__.cached)
    cached.write_bytes(cached.read_bytes()[:20])

    assert load_again(path, layout=layout).VALUE == 1


def test_nothing_is_written_when_python_is_told_not_to():
    root = write_files({"test_not_written.py": "VALUE = 1\n"})
    path = root / "test_not_written.py"

    with patch(sys, "dont_write_bytecode", True):
        module = loading.load_test_module(path, layout=layout_for(root))

    assert module.VALUE == 1
    assert not (root / "__pycache__").exists()


def test_a_helper_module_is_not_rewritten():
    root = write_files(
        {
            "loading_helpers_unrewritten.py": (
                "def check(value):\n    assert value == 1\n"
            ),
            "test_uses_unrewritten_helper.py": (
                "from loading_helpers_unrewritten import check\n"
            ),
        }
    )
    with patch(sys, "path", [str(root), *sys.path]):
        module = loading.load_test_module(
            root / "test_uses_unrewritten_helper.py", layout=layout_for(root)
        )

    helper = sys.modules["loading_helpers_unrewritten"]
    assert module.check is helper.check
    assert not isinstance(helper.__loader__, loading.TestModuleLoader)


def test_a_file_of_the_same_name_under_another_root_is_another_module():
    first_root = Path(tempfile.mkdtemp()).resolve()
    second_root = Path(tempfile.mkdtemp()).resolve()
    (first_root / "test_same_name.py").write_text("WHERE = 'first'\n")
    (second_root / "test_same_name.py").write_text("WHERE = 'second'\n")

    first = loading.load_test_module(
        first_root / "test_same_name.py", layout=layout_for(first_root)
    )
    second = loading.load_test_module(
        second_root / "test_same_name.py", layout=layout_for(second_root)
    )
    assert first.WHERE == "first"
    assert second.WHERE == "second"
    # And the same file is loaded once.
    again = loading.load_test_module(
        second_root / "test_same_name.py", layout=layout_for(second_root)
    )
    assert again is second
