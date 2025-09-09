import logging
from contextlib import contextmanager

from .debug import DebugMode


class AppLogger(logging.Logger):
    """Enhanced logger that supports kwargs-style logging and context management."""

    def __init__(self, name):
        super().__init__(name)
        self.context = {}  # Public, mutable context dict
        self.debug_mode = DebugMode(self)

    @contextmanager
    def include_context(self, **kwargs):
        """Context manager for temporary context."""
        # Store original context
        original_context = self.context.copy()

        # Add temporary context
        self.context.update(kwargs)

        try:
            yield
        finally:
            # Restore original context
            self.context = original_context

    def force_debug(self):
        """Return context manager for temporarily enabling DEBUG level logging."""
        return self.debug_mode

    # Override logging methods with explicit parameters for IDE support
    def debug(
        self,
        msg,
        *args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **context,
    ):
        if self.isEnabledFor(logging.DEBUG):
            self._log(
                logging.DEBUG,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                **context,
            )

    def info(
        self,
        msg,
        *args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **context,
    ):
        if self.isEnabledFor(logging.INFO):
            self._log(
                logging.INFO,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                **context,
            )

    def warning(
        self,
        msg,
        *args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **context,
    ):
        if self.isEnabledFor(logging.WARNING):
            self._log(
                logging.WARNING,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                **context,
            )

    def error(
        self,
        msg,
        *args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **context,
    ):
        if self.isEnabledFor(logging.ERROR):
            self._log(
                logging.ERROR,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                **context,
            )

    def critical(
        self,
        msg,
        *args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **context,
    ):
        if self.isEnabledFor(logging.CRITICAL):
            self._log(
                logging.CRITICAL,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                **context,
            )

    def _log(
        self,
        level,
        msg,
        args,
        exc_info=None,
        extra=None,
        stack_info=False,
        stacklevel=1,
        **context,
    ):
        """Low-level logging routine which creates a LogRecord and then calls all handlers."""
        # Check if extra already has a 'context' key
        if extra and "context" in extra:
            raise ValueError(
                "The 'context' key in extra is reserved for Plain's context system"
            )

        # Build final extra with context
        extra = extra.copy() if extra else {}

        # Add our context (persistent + kwargs) to extra["context"]
        if self.context or context:
            extra["context"] = {**self.context, **context}

        # Call the parent logger's _log method with explicit parameters
        super()._log(
            level=level,
            msg=msg,
            args=args,
            exc_info=exc_info,
            extra=extra or None,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )


# Create the default app logger instance
app_logger = AppLogger("app")
