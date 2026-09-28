"""`CaptureSource`: what a `capture_*` helper is built on.

Every capture of a kind reads from one list that grows as things happen. The
source is what lets them nest, and what empties the list when nobody is
capturing.
"""

from collections.abc import Generator
from contextlib import contextmanager

from plain.test import Captured, CaptureSource, raises


class Events:
    """A helper the way a package would write one, over a plain list."""

    def __init__(self) -> None:
        self.happened: list[str] = []
        self.source = CaptureSource(
            read=lambda: self.happened, clear=self.happened.clear
        )

    @contextmanager
    def capture_events(self) -> Generator[Captured[str]]:
        captured: Captured[str] = Captured(helper="capture_events")
        with self.source.capturing_into(captured):
            yield captured


def test_a_capture_gets_what_was_added_during_its_block():
    events = Events()
    events.happened.append("before")

    with events.capture_events() as captured:
        events.happened.append("during")

    assert captured == ["during"]


def test_a_capture_inside_another_leaves_the_outer_one_whole():
    events = Events()

    with events.capture_events() as outer:
        events.happened.append("first")
        with events.capture_events() as inner:
            events.happened.append("second")
        events.happened.append("third")

    assert inner == ["second"]
    assert outer == ["first", "second", "third"]


def test_the_list_is_emptied_when_the_outermost_capture_ends():
    events = Events()

    with events.capture_events() as outer:
        events.happened.append("first")
        with events.capture_events():
            events.happened.append("second")
        # An inner capture ending is not the end of capturing.
        assert events.happened == ["first", "second"]

    assert events.happened == []
    # What was captured is the capture's own, not a view of the list.
    assert outer == ["first", "second"]


def test_it_says_whether_a_capture_is_open():
    events = Events()
    assert not events.source.capturing

    with events.capture_events():
        assert events.source.capturing
        with events.capture_events():
            assert events.source.capturing
        assert events.source.capturing

    assert not events.source.capturing


def test_a_block_that_raises_still_finishes_and_empties():
    events = Events()

    with raises(ZeroDivisionError), events.capture_events() as captured:
        events.happened.append("first")
        1 / 0  # noqa: B018

    assert captured == ["first"]
    assert events.happened == []
    assert not events.source.capturing


def test_a_capture_is_finished_by_the_helper_that_made_it():
    captured: Captured[int] = Captured(helper="capture_numbers")
    assert not captured.finished

    captured.finish([1, 2])

    assert captured.finished
    assert captured == [1, 2]
