import logging
import threading


class DebugMode:
    """Context manager to temporarily set DEBUG level on a logger with reference counting."""

    def __init__(self, logger):
        self.logger = logger
        self.original_level = None
        self._ref_count = 0
        self._lock = threading.Lock()

    def __enter__(self):
        """Store original level and set to DEBUG."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore original level."""
        self.end()

    def start(self):
        """Enable DEBUG logging level."""
        with self._lock:
            if self._ref_count == 0:
                self.original_level = self.logger.level
                self.logger.setLevel(logging.DEBUG)
            self._ref_count += 1

    def end(self):
        """Restore original logging level."""
        with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count == 0:
                self.logger.setLevel(self.original_level)
