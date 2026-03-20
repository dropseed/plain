from __future__ import annotations

import logging
import sys
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import Any

from .debug import DebugMode


class PlainLogger(logging.Logger):
    """Enhanced logger that supports structured output and context management."""

    def __init__(self, name: str):
        super().__init__(name)
        self.context: dict[str, Any] = {}  # Public, mutable context dict
        self.debug_mode = DebugMode(self)

    @contextmanager
    def include_context(self, **kwargs: Any) -> Generator[None]:
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

    def force_debug(self) -> DebugMode:
        """Return context manager for temporarily enabling DEBUG level logging."""
        return self.debug_mode

    # Override logging methods to add context parameter for IDE support
    def debug(
        self,
        msg: object,
        *args: object,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self.isEnabledFor(logging.DEBUG):
            self._log(
                logging.DEBUG,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                context=context,
            )

    def info(
        self,
        msg: object,
        *args: object,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self.isEnabledFor(logging.INFO):
            self._log(
                logging.INFO,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                context=context,
            )

    def warning(
        self,
        msg: object,
        *args: object,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self.isEnabledFor(logging.WARNING):
            self._log(
                logging.WARNING,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                context=context,
            )

    def error(
        self,
        msg: object,
        *args: object,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self.isEnabledFor(logging.ERROR):
            self._log(
                logging.ERROR,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                context=context,
            )

    def critical(
        self,
        msg: object,
        *args: object,
        exc_info: Any = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self.isEnabledFor(logging.CRITICAL):
            self._log(
                logging.CRITICAL,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
                context=context,
            )

    def exception(
        self,
        msg: object,
        *args: object,
        exc_info: Any = True,
        stack_info: bool = False,
        stacklevel: int = 1,
        extra: Mapping[str, object] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.error(
            msg,
            *args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
            context=context,
        )

    def _log(
        self,
        level: int,
        msg: object,
        args: tuple[object, ...] | Mapping[str, object],
        exc_info: Any = None,
        extra: Mapping[str, object] | None = None,
        stack_info: bool = False,
        stacklevel: int = 1,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Low-level logging routine which creates a LogRecord and then calls all handlers."""

        # Merge into one dict: persistent context < extra < per-call context.
        # All keys end up as top-level attributes on the LogRecord.
        merged_extra: dict[str, object] = {}
        if self.context:
            merged_extra.update(self.context)
        if extra:
            merged_extra.update(extra)
        if context:
            merged_extra.update(context)

        super()._log(
            level=level,
            msg=msg,
            args=args,
            exc_info=exc_info,
            extra=merged_extra or None,
            stack_info=stack_info,
            stacklevel=stacklevel,
        )


def get_framework_logger(name: str = "") -> logging.Logger:
    """Get a logger for framework code with auto-derived naming.

    With no arguments, derives the name from the caller's module:
        plain.postgres.connection → plain.postgres
        plain.server.workers.entry → plain.server

    With an explicit name, uses it directly:
        get_framework_logger("plain.server.access")
    """
    if not name:
        caller = sys._getframe(1).f_globals["__name__"]
        parts = caller.split(".")
        name = ".".join(parts[:2])

    return logging.getLogger(name)


# Create the default app logger instance
app_logger = PlainLogger("app")
