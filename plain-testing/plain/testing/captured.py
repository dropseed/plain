"""
The shape every `capture_*` helper hands back.

A capture is a read-only sequence of what happened inside its block, in the
order it happened. It is complete when the block ends, so that is when it can
be read.

`Captured` is what a test reads. `CaptureSource` is for writing a
`capture_*` helper whose captures all read from one place, such as the span
exporter or a connection's query log.
"""

from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import overload

__all__ = ["CaptureSource", "Captured"]


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

    def finish(self, items: Iterable[T]) -> None:
        """
        Say what was captured. The helper that made this capture calls it
        when its block ends, and from then on the capture can be read.
        """
        self._items = tuple(items)

    @property
    def finished(self) -> bool:
        """Whether the block has ended, so the capture can be read."""
        return self._items is not None

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


class CaptureSource[T]:
    """
    The one place every capture of a kind reads from: the span exporter, a
    connection's query log. It is a list that grows as things happen, given
    here as a function that reads it and a function that empties it.

        _span_source = CaptureSource(
            read=exporter.get_finished_spans, clear=exporter.clear
        )

        @contextmanager
        def capture_spans():
            captured = CapturedSpans()
            with _span_source.capturing_into(captured):
                yield captured

    Captures nest: a project lifecycle can capture around every test, with
    the test's own capture inside it. So a capture doesn't empty the list
    when it starts. It remembers how long the list was, and gets what was
    added after that. The list is emptied when no capture is open: before
    the outermost one starts, and after it ends, so that nothing captured is
    kept for the rest of the run.
    """

    def __init__(
        self, *, read: Callable[[], Sequence[T]], clear: Callable[[], None]
    ) -> None:
        self._read = read
        self._clear = clear
        self._open_captures = 0

    @property
    def capturing(self) -> bool:
        """Whether any capture that reads from here is open."""
        return self._open_captures > 0

    @contextmanager
    def capturing_into(self, captured: Captured[T]) -> Generator[None]:
        """
        Capture for the duration of the block, and finish `captured` with
        what was added during it. A block that raises still finishes its
        capture.
        """
        if not self.capturing:
            self._clear()
        start = len(self._read())

        self._open_captures += 1
        try:
            yield
        finally:
            self._open_captures -= 1
            captured.finish(self._read()[start:])
            if not self.capturing:
                self._clear()
