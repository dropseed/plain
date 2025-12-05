from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType


class DebugMode:
    """Context manager to temporarily set DEBUG level on a logger with reference counting."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.original_level = None
        self._ref_count = 0
        self._lock = threading.Lock()

    def __enter__(self) -> DebugMode:
        """Store original level and set to DEBUG."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Restore original level."""
        self.end()

    def start(self) -> None:
        """Enable DEBUG logging level."""
        with self._lock:
            if self._ref_count == 0:
                self.original_level = self.logger.level
                self.logger.setLevel(logging.DEBUG)
            self._ref_count += 1

    def end(self) -> None:
        """Restore original logging level."""
        with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count == 0 and self.original_level is not None:
                self.logger.setLevel(self.original_level)
