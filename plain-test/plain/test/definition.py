"""
The one error for a test that is written in a way the runner can't run.
"""

__all__ = ["TestDefinitionError"]


class TestDefinitionError(Exception):
    """
    A test, or something the runner reads beside it, is written in a way
    that can't be run: a second `@cases`, a `@skip` with no reason, a
    parameter nothing passes in, a test that yields, an `import pytest`, a
    `conftest.py`, a `tests/lifecycle.py` that declares no lifecycle.

    Its message says what is wrong and what to write instead, so the runner
    prints the message on its own. Any other error met while reading a test
    file is printed with its traceback.

    `line` is the line of the file the message is about, when it is about
    one line.
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line
