from __future__ import annotations

import re
from types import TracebackType
from typing import Self

__all__ = ["raises"]


class raises[E: BaseException]:
    """
    Assert that a block raises one of the given exception types.

        with raises(ValidationError):
            validate_email("nope")

    The caught exception is available afterward, typed as what was caught —
    so its own attributes are reachable without a cast:

        with raises(ValidationError) as caught:
            validate_email("nope")
        assert "email" in caught.exception.messages

    Pass `match=` to also require the exception message to match a regex:

        with raises(ValueError, match="expected .* to be positive"):
            ...
    """

    def __init__(
        self,
        *exceptions: type[E],
        match: str | None = None,
    ) -> None:
        if not exceptions:
            raise TypeError("raises() requires at least one exception type")
        self.expected = exceptions
        self.match = match
        self._exception: E | None = None

    @property
    def exception(self) -> E:
        """
        The exception the block raised.

        Only readable once the block has exited — inside the block nothing has
        been caught yet, so reading it is a mistake worth saying out loud
        rather than handing back a None that fails somewhere later.
        """
        if self._exception is None:
            raise AttributeError(
                "raises(...).exception is only available after the `with` block "
                "exits — inside the block, the exception hasn't been raised yet."
            )
        return self._exception

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            expected_names = " or ".join(e.__name__ for e in self.expected)
            raise AssertionError(f"{expected_names} was not raised")

        if not issubclass(exc_type, self.expected):
            # Let the unexpected exception propagate.
            return False

        assert exc is not None
        self._exception = exc  # ty: ignore[invalid-assignment] (narrowed by issubclass above)

        if self.match is not None and not re.search(self.match, str(exc)):
            raise AssertionError(
                f"{exc_type.__name__} was raised, but its message did not match {self.match!r}\n"
                f"  message: {str(exc)!r}"
            ) from exc

        return True
