"""
What a run writes to stdout and stderr, held until it is known whether
anyone needs to read it.

A test that passes wrote nothing worth reading, and what it wrote is thrown
away. A test that fails has what it wrote printed with its failure, and
nowhere else.

The two descriptors themselves are pointed at files, 1 and 2, not
`sys.stdout` and `sys.stderr`. Replacing those two names would miss most of
what a test writes: a logging handler keeps the stream object it was given
when logging was configured, before any test ran; a subprocess and a C
extension write to the descriptor and never look at `sys`. Everything that
writes ends up at the descriptor, so that is where it is held.

The runner's own output goes to the descriptors as they were, through
`real_stdout` and `real_stderr`.
"""

import codecs
import faulthandler
import os
import sys
import tempfile
from dataclasses import dataclass
from types import TracebackType
from typing import IO, Self, TextIO

__all__ = []

# The most of one stream that is kept for one test, in characters. What is
# kept is the end: the last thing written is the nearest to the failure.
OUTPUT_CAP = 10_000

# The flag that lets output through as it is written.
SHOW_OUTPUT_FLAG = "--show-output"

_READ_AT_ONCE = 1024 * 1024


@dataclass(frozen=True, kw_only=True)
class StreamOutput:
    """What was written to one stream, as a report prints it."""

    text: str
    # How many characters the cap left out, from the start. 0 when `text`
    # is everything that was written.
    cut_characters: int = 0


@dataclass(frozen=True, kw_only=True)
class Output:
    """What was written to stdout and to stderr, each in its own order."""

    stdout: StreamOutput
    stderr: StreamOutput

    def __bool__(self) -> bool:
        return bool(self.stdout.text or self.stderr.text)


NO_OUTPUT = Output(stdout=StreamOutput(text=""), stderr=StreamOutput(text=""))


class _HeldDescriptor:
    """One of the process's output descriptors, pointed at a file."""

    def __init__(self, descriptor: int) -> None:
        self.descriptor = descriptor
        self.real = os.dup(descriptor)
        self.file, self.path_still_to_remove = _file_that_appends()
        self.hold()

    def hold(self) -> None:
        os.dup2(self.file.fileno(), self.descriptor)

    def let_through(self) -> None:
        os.dup2(self.real, self.descriptor)

    def close(self) -> None:
        self.let_through()
        os.close(self.real)
        self.file.close()
        if self.path_still_to_remove is not None:
            os.unlink(self.path_still_to_remove)

    def empty(self) -> None:
        self.file.truncate(0)

    def written(self, *, full_output: bool) -> StreamOutput:
        size = os.fstat(self.file.fileno()).st_size
        if size == 0:
            return StreamOutput(text="")

        if full_output:
            self.file.seek(0)
            return StreamOutput(text=self.file.read().decode(errors="replace"))

        # A character is at most four bytes, so the last OUTPUT_CAP
        # characters are within the last four times as many bytes.
        kept_from = max(0, size - OUTPUT_CAP * 4)
        self.file.seek(kept_from)
        text = self.file.read().decode(errors="replace")
        if kept_from == 0 and len(text) <= OUTPUT_CAP:
            return StreamOutput(text=text)

        kept = text[-OUTPUT_CAP:]
        return StreamOutput(
            text=kept, cut_characters=self._characters_in_file() - len(kept)
        )

    def _characters_in_file(self) -> int:
        """Counted a piece at a time: the file can be any size."""
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        characters = 0
        self.file.seek(0)
        while piece := self.file.read(_READ_AT_ONCE):
            characters += len(decoder.decode(piece))
        return characters + len(decoder.decode(b"", final=True))


class OutputCapture:
    """
    Holds what is written to stdout and stderr from entering to exiting.

        with OutputCapture() as capture:
            ...
            output = capture.take()

    With `show_output`, nothing is held: output goes where it always went,
    as it is written, and `take()` has nothing to give.
    """

    def __init__(self, *, show_output: bool = False, full_output: bool = False) -> None:
        self.show_output = show_output
        self.full_output = full_output
        self.real_stdout: TextIO = sys.stdout
        self.real_stderr: TextIO = sys.stderr
        self._held: list[_HeldDescriptor] = []
        self._let_through_for_a_debugger = False
        self._fault_handler_was_enabled = False
        self._stdout_wrote_a_line_at_a_time = False
        self._previous_breakpoint_hook = sys.breakpointhook

    def __enter__(self) -> Self:
        if self.show_output:
            return self

        _flush_what_python_is_holding()
        stdout = _HeldDescriptor(1)
        stderr = _HeldDescriptor(2)
        self._held = [stdout, stderr]

        # Python writes what is printed when it has a few thousand
        # characters of it, unless stdout is a terminal. A line printed
        # before a subprocess ran would be written after what the
        # subprocess wrote. Written a line at a time, what is held is in
        # the order it was written in.
        self._stdout_wrote_a_line_at_a_time = _line_buffering_of(sys.stdout)
        _write_a_line_at_a_time(sys.stdout, True)
        self.real_stdout = _text_stream(stdout.real, like=sys.stdout)
        self.real_stderr = _text_stream(stderr.real, like=sys.stderr)

        # A crash of the interpreter itself is reported on stderr, by
        # `faulthandler`. It must reach the terminal: nothing would be left
        # running to print what was held.
        self._fault_handler_was_enabled = faulthandler.is_enabled()
        faulthandler.enable(file=self.real_stderr)

        # A debugger needs the terminal.
        self._previous_breakpoint_hook = sys.breakpointhook
        sys.breakpointhook = self._breakpoint  # ty: ignore[invalid-assignment]
        return self

    def __exit__(
        self,
        error_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.show_output:
            return

        # An error on its way out of the runner is about to be printed by
        # Python, with nothing of the runner's left to print what was held
        # before it. So it is printed here, as it was written.
        held = NO_OUTPUT
        if error is not None and not isinstance(error, SystemExit):
            held = self.take()

        sys.breakpointhook = self._previous_breakpoint_hook  # ty: ignore[invalid-assignment]
        if self._fault_handler_was_enabled:
            faulthandler.enable()
        else:
            faulthandler.disable()

        _flush_what_python_is_holding()
        _write_a_line_at_a_time(sys.stdout, self._stdout_wrote_a_line_at_a_time)
        self.real_stdout.flush()
        self.real_stderr.flush()
        for descriptor in self._held:
            descriptor.close()
        self._held = []
        self.real_stdout = sys.stdout
        self.real_stderr = sys.stderr

        if held:
            sys.stdout.write(held.stdout.text)
            sys.stdout.flush()
            sys.stderr.write(held.stderr.text)
            sys.stderr.flush()

    def take(self) -> Output:
        """What has been written since the last `take()` or `discard()`."""
        if not self._held:
            return NO_OUTPUT

        _flush_what_python_is_holding()
        stdout, stderr = self._held
        output = Output(
            stdout=stdout.written(full_output=self.full_output),
            stderr=stderr.written(full_output=self.full_output),
        )
        self._empty()
        return output

    def discard(self) -> None:
        """Throw away what has been written since the last `take()`."""
        if not self._held:
            return

        _flush_what_python_is_holding()
        self._empty()

    def _empty(self) -> None:
        for descriptor in self._held:
            descriptor.empty()
        # A debugger had the terminal until the test it was in was over.
        if self._let_through_for_a_debugger:
            self._let_through_for_a_debugger = False
            for descriptor in self._held:
                descriptor.hold()

    def _breakpoint(self, *args: object, **kwargs: object) -> object:
        """
        What `breakpoint()` calls during a run. Output is let through from
        here until the test is over, and then the debugger is started as
        it would have been.
        """
        if os.environ.get("PYTHONBREAKPOINT") == "0":
            return None

        self._let_output_through_for_a_debugger()

        if os.environ.get("PYTHONBREAKPOINT", "pdb.set_trace") != "pdb.set_trace":
            return sys.__breakpointhook__(*args, **kwargs)  # noqa: T100 — starting the debugger that was asked for

        # Imported here: pdb takes longer to import than most runs take to
        # collect, and nearly no run uses it.
        import pdb  # noqa: T100

        # Started on the frame that called `breakpoint()`, as `pdb.set_trace()`
        # starts it. Left to find the frame for itself, pdb would find this
        # one.
        debugger = pdb.Pdb(mode="inline", backend="monitoring", colorize=True)
        debugger.set_trace(sys._getframe(1))
        return None

    def _let_output_through_for_a_debugger(self) -> None:
        if self._let_through_for_a_debugger:
            return
        _flush_what_python_is_holding()
        for descriptor in self._held:
            descriptor.let_through()
        self._let_through_for_a_debugger = True
        self.real_stderr.write(
            "\nbreakpoint(): output is let through until this test is over.\n"
        )
        self.real_stderr.flush()


def _file_that_appends() -> tuple[IO[bytes], str | None]:
    """
    A temporary file that every write is added to the end of, whoever
    writes and wherever they think they are in it. Once the file has been
    emptied, the end is the start again.

    It is opened by its path for that. `tempfile.TemporaryFile(mode="a+b")`
    opens the file first and is given the mode afterwards, which is too
    late to make the descriptor an appending one.
    """
    descriptor, path = tempfile.mkstemp(prefix="plain-test-output-")
    os.close(descriptor)
    file = open(path, "a+b", buffering=0)  # noqa: SIM115 — it is held open for the run
    # Nothing else needs its name, and without one the file is gone when it
    # is closed. Windows won't take the name off a file that is open: there
    # the path is returned too, to be removed after closing.
    try:
        os.unlink(path)
    except PermissionError:
        return file, path
    return file, None


def _text_stream(descriptor: int, *, like: TextIO) -> TextIO:
    """A stream that writes text to a descriptor, a line at a time."""
    return os.fdopen(
        descriptor,
        "w",
        buffering=1,
        encoding=getattr(like, "encoding", None) or "utf-8",
        errors="backslashreplace",
        closefd=False,
    )


def _line_buffering_of(stream: TextIO) -> bool:
    return bool(getattr(stream, "line_buffering", False))


def _write_a_line_at_a_time(stream: TextIO, line_buffering: bool) -> None:
    # A test run inside another test's `redirect_stdout` has a stream here
    # that can't be told how to write, and doesn't write to the descriptor.
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(line_buffering=line_buffering)


def _flush_what_python_is_holding() -> None:
    """
    Python keeps what is written to `sys.stdout` for a while before writing
    it to the descriptor. It has to be written before the descriptor is
    read, emptied or pointed somewhere else.
    """
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        if stream is None:
            continue
        try:
            stream.flush()
        except ValueError, OSError:
            # Closed, by the test that replaced it.
            pass
