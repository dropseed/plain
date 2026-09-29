"""What `plain docs <name> --api` prints for a source file."""

import tempfile
from pathlib import Path

from plain.cli.llmdocs import LLMDocs

SOURCE = '''
from dataclasses import dataclass


@dataclass(frozen=True)
class Thing:
    """A docstring, which isn't part of the API listing."""

    id: str
    tags: tuple[str, ...] = ()
    plain_default = 1
    _private: int = 0

    def name(self) -> str:
        return self.id

    @_checks_its_arguments
    def send(self, to: str) -> None:
        pass

    def _hidden(self) -> None:
        pass


public_setting: int = 3
unlisted_setting: int = 4
'''


def symbolicate(public_symbols: set[str] | None) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        source_file = Path(tmp) / "things.py"
        source_file.write_text(SOURCE)
        return LLMDocs.symbolicate(source_file, public_symbols).splitlines()


def test_annotated_attributes_are_listed_with_their_annotation():
    assert symbolicate({"Thing"}) == [
        "@dataclass(frozen=True)",
        "class Thing()",
        "    id: str",
        "    tags: tuple[str, ...] = ()",
        "    plain_default = 1",
        "    def name(self)",
        "    def send(self, to: str)",
    ]


def test_an_annotated_module_variable_is_listed_when_it_is_public():
    assert symbolicate({"public_setting"}) == ["public_setting: int = 3"]


def test_a_private_decorator_is_left_out_and_a_public_one_is_listed():
    lines = symbolicate({"Thing"})

    assert "@dataclass(frozen=True)" in lines
    assert "    @_checks_its_arguments" not in lines
