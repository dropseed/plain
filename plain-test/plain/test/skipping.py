"""
Skipping a test from inside its body.

`@skip` declares that a test never runs. `skip_test()` is for the case only
the running test can see — a condition computed from its arguments, or an
outcome it has to try for first.
"""

from typing import NoReturn

__all__ = ["TestSkipped", "skip_test"]


class TestSkipped(BaseException):
    """
    Raised by `skip_test()`. The runner reports the test as skipped.

    A BaseException, so an `except Exception:` in the test or in the code it
    exercises can't swallow the skip and let the test carry on.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def skip_test(reason: str) -> NoReturn:
    """
    Stop this test here and report it as skipped, with the reason shown.

        def test_upload_to_bucket():
            if not bucket_is_reachable():
                skip_test("No bucket reachable from this machine")
            ...

    Everything the test entered is still exited: `with` blocks unwind, and
    the database transaction is rolled back like any other test's.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise TypeError('skip_test() requires a reason: skip_test("why")')
    raise TestSkipped(reason)
