"""
Capture log records emitted during a block.

The framework's own loggers don't propagate to the root logger, so a
root-attached handler sees nothing. `capture_logs` attaches directly to the
loggers you name (by default the whole `plain` and `app` trees) and takes them
down again on exit.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from opentelemetry.trace import SpanContext

__all__ = ["CapturedLogs", "capture_logs"]

# The trees Plain code logs into. `plain.mcp`, `plain.jobs` and friends
# propagate up to `plain`, so naming the root of each tree catches them all.
DEFAULT_LOGGER_NAMES = ("plain", "app")


class _RecordingHandler(logging.Handler):
    """Records each emit alongside the span context current at that moment.

    The span context is kept beside the record rather than set on it. A
    LogRecord's `__dict__` is how Plain carries structured context (see
    `plain.logs.formatters`), so an extra attribute here would show up as a
    key=value pair in every other handler's output — including the OTel
    LoggingHandler's exported attributes.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.span_contexts: list[SpanContext] = []
        # One handler can be attached to several loggers at once (the default
        # is two). A record that reaches more than one of them is still one
        # record, so it's counted once.
        self._seen: set[int] = set()

    def emit(self, record: logging.LogRecord) -> None:
        if id(record) in self._seen:
            return
        self._seen.add(id(record))

        from opentelemetry.trace import get_current_span

        self.records.append(record)
        self.span_contexts.append(get_current_span().get_span_context())


class CapturedLogs(Sequence[logging.LogRecord]):
    """
    The records captured by `capture_logs`, in emission order.

    Behaves like a list of `logging.LogRecord`, so iteration, indexing and
    `len()` all work directly.
    """

    def __init__(self, handler: _RecordingHandler) -> None:
        self._handler = handler

    @property
    def records(self) -> list[logging.LogRecord]:
        return self._handler.records

    @property
    def messages(self) -> list[str]:
        """The formatted message of every captured record."""
        return [record.getMessage() for record in self._handler.records]

    def __len__(self) -> int:
        return len(self._handler.records)

    @overload
    def __getitem__(self, index: int) -> logging.LogRecord: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[logging.LogRecord]: ...

    def __getitem__(
        self, index: int | slice
    ) -> logging.LogRecord | Sequence[logging.LogRecord]:
        return self._handler.records[index]

    def __iter__(self) -> Iterator[logging.LogRecord]:
        return iter(self._handler.records)

    def __repr__(self) -> str:
        return f"<CapturedLogs {self.messages!r}>"

    def span_context_for(self, message: str) -> SpanContext:
        """
        The OpenTelemetry span context that was current when the record with
        this message was emitted.

            with capture_spans() as spans, capture_logs() as logs:
                do_the_thing()

            span = spans.find(name="claim job")
            assert logs.span_context_for("Claim failed").trace_id == (
                span.context.trace_id
            )

        A log emitted with no span current has an invalid (all-zero) context,
        which is what an exporter would ship — that's the failure this is
        usually asserting against. Raises if the message wasn't logged exactly
        once, so a typo or a duplicate can't pass silently.
        """
        matches = [
            context
            for record, context in zip(
                self._handler.records, self._handler.span_contexts, strict=True
            )
            if record.getMessage() == message
        ]
        if not matches:
            raise LookupError(
                f"No log record with message {message!r}. Captured: {self.messages!r}"
            )
        if len(matches) > 1:
            raise LookupError(
                f"{len(matches)} log records with message {message!r} — "
                "span_context_for needs exactly one."
            )
        return matches[0]


@contextmanager
def capture_logs(
    *logger_names: str, level: int = logging.DEBUG
) -> Generator[CapturedLogs]:
    """
    The log records emitted during the block.

        with capture_logs() as logs:
            Client().get("/boom/")

        assert "Server error" in logs.messages
        assert logs[0].path == "/boom/"

    With no arguments this captures the `plain` and `app` trees. Name loggers
    to narrow it:

        with capture_logs("plain.jobs") as logs:
            ...

    Each logger's level is lowered for the block and restored on exit, as is
    any global `logging.disable()` in effect — otherwise a level set elsewhere
    could swallow the records under test.
    """
    names = logger_names or DEFAULT_LOGGER_NAMES
    handler = _RecordingHandler()
    loggers = [logging.getLogger(name) for name in names]

    original_levels = [logger.level for logger in loggers]
    original_disable = logging.root.manager.disable

    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(level)
    logging.root.manager.disable = 0
    try:
        yield CapturedLogs(handler)
    finally:
        logging.root.manager.disable = original_disable
        for logger, original_level in zip(loggers, original_levels, strict=True):
            logger.removeHandler(handler)
            logger.setLevel(original_level)
