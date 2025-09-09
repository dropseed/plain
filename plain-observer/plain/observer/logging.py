import logging
import threading
from datetime import UTC, datetime

from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id

from .core import ObserverMode
from .otel import get_observer_span_processor


class ObserverLogHandler(logging.Handler):
    """Custom logging handler that captures logs during active traces when observer is enabled."""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        self._logs_lock = threading.Lock()
        # Store logs per trace_id
        self._trace_logs = {}  # trace_id -> list of log records

    def emit(self, record):
        """Emit a log record if we're in an active observer trace."""
        try:
            # Get the current span to determine if we're in an active trace
            current_span = trace.get_current_span()
            if not current_span or not current_span.get_span_context().is_valid:
                return

            # Get trace and span IDs
            trace_id = f"0x{format_trace_id(current_span.get_span_context().trace_id)}"
            span_id = f"0x{format_span_id(current_span.get_span_context().span_id)}"

            # Check if observer is recording this trace
            processor = get_observer_span_processor()
            if not processor:
                return

            # Check if we should record logs for this trace
            with processor._traces_lock:
                if trace_id not in processor._traces:
                    return

                trace_info = processor._traces[trace_id]
                # Only capture logs in PERSIST mode
                if trace_info["mode"] != ObserverMode.PERSIST.value:
                    return

            # Store the log record with span context
            log_entry = {
                "record": record,
                "span_id": span_id,
                "timestamp": datetime.fromtimestamp(record.created, tz=UTC),
            }

            with self._logs_lock:
                if trace_id not in self._trace_logs:
                    self._trace_logs[trace_id] = []
                self._trace_logs[trace_id].append(log_entry)

                # Limit logs per trace to prevent memory issues
                if len(self._trace_logs[trace_id]) > 1000:
                    self._trace_logs[trace_id] = self._trace_logs[trace_id][-500:]

        except Exception:
            # Don't let logging errors break the application
            pass

    def get_logs_for_trace(self, trace_id):
        """Get all logs for a specific trace."""
        with self._logs_lock:
            return self._trace_logs.get(trace_id, []).copy()

    def clear_trace_logs(self, trace_id):
        """Clear logs for a specific trace (called when trace completes)."""
        with self._logs_lock:
            self._trace_logs.pop(trace_id, None)

    def cleanup_old_traces(self, active_trace_ids):
        """Remove logs for traces that are no longer active."""
        with self._logs_lock:
            # Keep only logs for active traces
            self._trace_logs = {
                trace_id: logs
                for trace_id, logs in self._trace_logs.items()
                if trace_id in active_trace_ids
            }


# Global instance of the log handler
_observer_log_handler = None


def get_observer_log_handler():
    """Get the global observer log handler instance."""
    global _observer_log_handler
    if _observer_log_handler is None:
        _observer_log_handler = ObserverLogHandler()
    return _observer_log_handler


def install_observer_log_handler():
    """Install the observer log handler to the root logger."""
    handler = get_observer_log_handler()

    # Don't add if already installed
    root_logger = logging.getLogger()
    if handler not in root_logger.handlers:
        root_logger.addHandler(handler)

        # Also install on common app loggers
        for logger_name in ["app", "plain"]:
            logger_obj = logging.getLogger(logger_name)
            if handler not in logger_obj.handlers:
                logger_obj.addHandler(handler)


def uninstall_observer_log_handler():
    """Remove the observer log handler from the root logger."""
    global _observer_log_handler
    if _observer_log_handler:
        root_logger = logging.getLogger()
        if _observer_log_handler in root_logger.handlers:
            root_logger.removeHandler(_observer_log_handler)
