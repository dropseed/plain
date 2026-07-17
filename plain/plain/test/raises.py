from __future__ import annotations

import re
from types import TracebackType

__all__ = ["raises"]


class raises:
    """
    Assert that a block raises one of the given exception types.

        with raises(ValidationError):
            validate_email("nope")

    The caught exception is available afterward:

        with raises(ValidationError) as caught:
            validate_email("nope")
        assert "email" in str(caught.exception)

    Pass `match=` to also require the exception message to match a regex:

        with raises(ValueError, match="expected .* to be positive"):
            ...
    """

    def __init__(
        self,
        *exceptions: type[BaseException],
        match: str | None = None,
    ) -> None:
        if not exceptions:
            raise TypeError("raises() requires at least one exception type")
        self.expected = exceptions
        self.match = match
        self.exception: BaseException | None = None

    def __enter__(self) -> raises:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        expected_names = " or ".join(e.__name__ for e in self.expected)

        if exc_type is None:
            raise AssertionError(f"{expected_names} was not raised")

        if not issubclass(exc_type, self.expected):
            # Let the unexpected exception propagate.
            return False

        assert exc is not None
        self.exception = exc

        if self.match is not None and not re.search(self.match, str(exc)):
            raise AssertionError(
                f"{exc_type.__name__} was raised, but its message did not match {self.match!r}\n"
                f"  message: {str(exc)!r}"
            ) from exc

        return True
