from __future__ import annotations

import linecache
import logging
import reprlib
import traceback
from types import FrameType, TracebackType
from typing import Any

from plain.runtime import settings

logger = logging.getLogger(__name__)


class ExceptionFrame:
    """Information about a single traceback frame."""

    def __init__(
        self, frame: FrameType, lineno: int, *, capture_locals: bool = False
    ) -> None:
        self.filename = frame.f_code.co_filename
        self.lineno = lineno
        self.name = frame.f_code.co_name
        self.category = self._get_category(self.filename)
        self.source_lines: list[dict[str, Any]] = self._extract_source_lines(
            self.filename, lineno
        )
        self.locals: list[dict[str, str]] = (
            self._extract_locals(frame.f_locals) if capture_locals else []
        )

    @staticmethod
    def _get_category(filename: str) -> str:
        """Categorize a frame by its source: app, plain, plainx, python, or third-party."""
        # Python stdlib
        if "lib/python" in filename and "site-packages" not in filename:
            return "python"

        # Plain framework - core and extension packages
        # Installed: site-packages/plain/
        # Local dev: /plain/plain/ or /plain-*/plain/
        if (
            "site-packages/plain/" in filename
            or "/plain/plain/" in filename
            or "/plain-" in filename
        ):
            return "plain"

        # Plainx community packages (separate namespace)
        # Installed: site-packages/plainx/
        # Local dev: /plainx/ or /plainx-*/plainx/
        if "site-packages/plainx/" in filename or "/plainx" in filename:
            return "plainx"

        # Third-party packages
        if "site-packages" in filename or "dist-packages" in filename:
            return "third-party"

        # Everything else is app code
        return "app"

    @staticmethod
    def _extract_source_lines(
        filename: str, lineno: int, context_lines: int = 5
    ) -> list[dict[str, Any]]:
        """Extract source code lines around the error line."""
        source_lines = []
        start = max(1, lineno - context_lines)
        end = lineno + context_lines + 1

        for i in range(start, end):
            line = linecache.getline(filename, i)
            if line:
                source_lines.append(
                    {
                        "lineno": i,
                        "code": line.rstrip("\n"),
                        "is_error_line": i == lineno,
                    }
                )

        return source_lines

    @staticmethod
    def _safe_repr(value: Any, max_length: int = 200) -> str:
        """Safely repr a value, handling large objects and errors."""
        try:
            r = reprlib.Repr()
            r.maxstring = max_length
            r.maxother = max_length
            return r.repr(value)
        except Exception:
            return f"<{type(value).__name__}>"

    @classmethod
    def _extract_locals(cls, f_locals: dict[str, Any]) -> list[dict[str, str]]:
        """Extract local variables for display, sorted alphabetically."""
        result = []
        for name in sorted(f_locals.keys()):
            if name.startswith("_"):  # Skip private/dunder vars
                continue
            value = f_locals[name]
            result.append(
                {
                    "name": name,
                    "value": cls._safe_repr(value),
                    "type": type(value).__name__,
                }
            )
        return result

    @classmethod
    def from_traceback(cls, tb: TracebackType | None) -> list[ExceptionFrame]:
        """Extract all frames from a traceback."""
        if tb is None:
            return []

        # Only capture locals in DEBUG mode to avoid exposing sensitive data in production
        capture_locals = settings.DEBUG

        frames = []
        current_tb = tb

        while current_tb is not None:
            frames.append(
                cls(
                    current_tb.tb_frame,
                    current_tb.tb_lineno,
                    capture_locals=capture_locals,
                )
            )
            current_tb = current_tb.tb_next

        return frames


class ExceptionContext:
    """Wrapper for exception with traceback data for template rendering."""

    def __init__(self, exception: BaseException) -> None:
        self.exception = exception
        self.traceback_string: str = "".join(
            traceback.format_tb(exception.__traceback__)
        )

        # Extract frames with source context (more complex, may fail)
        try:
            self.traceback_frames: list[ExceptionFrame] = list(
                reversed(ExceptionFrame.from_traceback(exception.__traceback__))
            )
        except Exception:
            logger.exception("Failed to extract traceback frames")
            self.traceback_frames = []
