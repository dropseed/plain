"""Log capture for tests.

`plain.test` has no log-capture helper yet, so tests that need to assert on
emitted records attach a recording handler themselves. This is the one
implementation the `plain` suite shares.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def capture_logs(
    logger_name: str, *, level: int = logging.NOTSET
) -> Generator[list[logging.LogRecord]]:
    """Collect the records `logger_name` (and its children) emit in the block.

        with capture_logs("plain.server", level=logging.ERROR) as records:
            ...
        assert [r.getMessage() for r in records] == ["Unexpected connection error"]

    The logger's level and propagation are restored on exit.
    """
    logger = logging.getLogger(logger_name)
    handler = _RecordingHandler()

    original_level = logger.level
    original_disabled = logger.manager.disable

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.manager.disable = 0
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.manager.disable = original_disabled
