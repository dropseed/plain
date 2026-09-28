"""
The one error for a test that is written in a way the runner can't run.
"""

__all__ = ["TestDefinitionError"]


class TestDefinitionError(Exception):
    """
    A test, or something the runner reads beside it, is written in a way
    that can't be run: a second `@cases`, a `@skip` with no reason, a
    parameter nothing passes in, a `conftest.py`, a `tests/lifecycle.py`
    that declares no lifecycle.

    Its message says what is wrong and what to write instead, so the runner
    prints the message on its own. Any other error met while reading a test
    file is printed with its traceback.
    """
