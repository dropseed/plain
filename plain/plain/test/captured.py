"""
The shape every `capture_*` helper hands back.

A capture is a read-only sequence of what happened inside its block, in the
order it happened. It is complete when the block ends, so that is when it can
be read.
"""

from collections.abc import Iterable, Iterator, Sequence
from typing import overload

__all__ = ["Captured"]


class Captured[T](Sequence[T]):
    """
    What a `capture_*` block recorded, in the order it happened.

        with capture_spans() as spans:
            Client().get("/")

        assert len(spans) == 1
        assert spans[0].name == "GET /"

    It's a sequence, so `len()`, indexing, slicing, iteration, `in` and
    truthiness all work, and nothing can be added to it or removed from it.
    It compares equal to a list or tuple holding the same items.

    Read it after the block. Inside the block the capture is still going — a
    span that hasn't ended or a metric that hasn't been collected isn't there
    yet — so reading it raises instead of answering with part of the story.
    """

    def __init__(self, *, helper: str) -> None:
        # The helper's name, for the messages: "capture_spans".
        self._helper = helper
        self._items: tuple[T, ...] | None = None

    def _finish(self, items: Iterable[T]) -> None:
        """Called by the helper when its block ends."""
        self._items = tuple(items)

    def _finished_items(self) -> tuple[T, ...]:
        if self._items is None:
            raise RuntimeError(
                f"{self._helper}() is still capturing — read what it captured"
                f" after the `with {self._helper}()` block ends, not inside it."
            )
        return self._items

    def __len__(self) -> int:
        return len(self._finished_items())

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[T]: ...

    def __getitem__(self, index: int | slice) -> T | Sequence[T]:
        return self._finished_items()[index]

    def __iter__(self) -> Iterator[T]:
        return iter(self._finished_items())

    def __eq__(self, other: object) -> bool:
        # Equal to a list or tuple of the same items, so `captured == []`
        # says what it looks like it says instead of always being False.
        if isinstance(other, Captured):
            return self._finished_items() == other._finished_items()
        if isinstance(other, list | tuple):
            return list(self._finished_items()) == list(other)
        return NotImplemented

    def __repr__(self) -> str:
        if self._items is None:
            return f"<{type(self).__name__}: still capturing>"
        return f"<{type(self).__name__} {list(self._items)!r}>"
