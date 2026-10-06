"""
The mechanics of holding output: what is written to the two descriptors
while an `OutputCapture` is entered, and what it gives back.

These run inside a run that is holding output itself. A capture entered
inside another holds what the outer one would have, and gives the
descriptors back as it found them.
"""

import os
import sys

from plain.testing import raises
from plain.testing.runner.output_capture import (
    NO_OUTPUT,
    OUTPUT_CAP,
    OutputCapture,
    StreamOutput,
)


def test_take_gives_what_was_written_since_the_last_take():
    with OutputCapture() as capture:
        print("first")
        first = capture.take()
        print("second")
        print("to stderr", file=sys.stderr)
        second = capture.take()
        nothing = capture.take()

    assert first.stdout == StreamOutput(text="first\n")
    assert second.stdout == StreamOutput(text="second\n")
    assert second.stderr == StreamOutput(text="to stderr\n")
    assert nothing == NO_OUTPUT
    assert not nothing


def test_discard_throws_away_what_was_written():
    with OutputCapture() as capture:
        print("thrown away")
        capture.discard()
        os.write(1, b"kept\n")
        output = capture.take()

    assert output.stdout.text == "kept\n"


def test_what_is_held_is_in_the_order_it_was_written():
    with OutputCapture() as capture:
        print("printed first")
        os.write(1, b"written to the descriptor second\n")
        print("printed third")
        output = capture.take()

    assert output.stdout.text.splitlines() == [
        "printed first",
        "written to the descriptor second",
        "printed third",
    ]


def test_the_end_is_kept_and_the_start_is_counted():
    with OutputCapture() as capture:
        os.write(1, b"a" * 25 + b"b" * OUTPUT_CAP)
        output = capture.take()

    assert output.stdout.text == "b" * OUTPUT_CAP
    assert output.stdout.cut_characters == 25


def test_characters_are_counted_not_bytes():
    # Three bytes each.
    with OutputCapture() as capture:
        os.write(1, ("€" * (OUTPUT_CAP + 7)).encode())
        output = capture.take()

    assert output.stdout.text == "€" * OUTPUT_CAP
    assert output.stdout.cut_characters == 7


def test_full_output_keeps_everything():
    with OutputCapture(full_output=True) as capture:
        os.write(1, b"a" * (OUTPUT_CAP * 3))
        output = capture.take()

    assert len(output.stdout.text) == OUTPUT_CAP * 3
    assert output.stdout.cut_characters == 0


def test_bytes_that_are_not_text_are_printed_as_not_text():
    with OutputCapture() as capture:
        os.write(1, b"before \xff\xfe after\n")
        output = capture.take()

    assert output.stdout.text == "before �� after\n"


def test_the_descriptors_are_given_back_as_they_were():
    before = os.fstat(1), os.fstat(2)
    with OutputCapture():
        during = os.fstat(1), os.fstat(2)
    after = os.fstat(1), os.fstat(2)

    assert during != before
    assert after == before


def test_the_descriptors_are_given_back_when_the_block_raises():
    before = os.fstat(1)
    with raises(RuntimeError), OutputCapture():
        raise RuntimeError("boom")

    assert os.fstat(1) == before


def test_the_runners_own_output_is_not_held():
    with OutputCapture() as capture:
        capture.real_stdout.write("the runner's own\n")
        capture.real_stdout.flush()
        output = capture.take()

    assert output == NO_OUTPUT


def test_show_output_holds_nothing():
    before = os.fstat(1)
    with OutputCapture(show_output=True) as capture:
        assert os.fstat(1) == before
        assert capture.real_stdout is sys.stdout
        print("let through")
        output = capture.take()

    assert output == NO_OUTPUT


def test_breakpoint_is_given_back_too():
    before = sys.breakpointhook
    with OutputCapture():
        assert sys.breakpointhook is not before
    assert sys.breakpointhook is before
