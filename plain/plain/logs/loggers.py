import logging
import threading

app_logger = logging.getLogger("app")


class KVLogger:
    def __init__(self, logger):
        self.logger = logger
        self.context = {}  # A dict that will be output in every log message

    def log(self, level, message, **kwargs):
        msg_kwargs = {
            **kwargs,
            **self.context,  # Put these last so they're at the end of the line
        }
        self.logger.log(level, f"{message} {self._format_kwargs(msg_kwargs)}")

    def _format_kwargs(self, kwargs):
        outputs = []

        for k, v in kwargs.items():
            self._validate_key(k)
            formatted_value = self._format_value(v)
            outputs.append(f"{k}={formatted_value}")

        return " ".join(outputs)

    def _validate_key(self, key):
        if " " in key:
            raise ValueError("Keys cannot have spaces")

        if "=" in key:
            raise ValueError("Keys cannot have equals signs")

        if '"' in key or "'" in key:
            raise ValueError("Keys cannot have quotes")

    def _format_value(self, value):
        if isinstance(value, str):
            s = value
        else:
            s = str(value)

        if '"' in s:
            # Escape quotes and surround it
            s = s.replace('"', '\\"')
            s = f'"{s}"'
        elif s == "":
            # Quote empty strings instead of printing nothing
            s = '""'
        elif any(char in s for char in [" ", "/", "'", ":", "=", "."]):
            # Surround these with quotes for parsers
            s = f'"{s}"'

        return s

    def info(self, message, **kwargs):
        self.log(logging.INFO, message, **kwargs)

    def debug(self, message, **kwargs):
        self.log(logging.DEBUG, message, **kwargs)

    def warning(self, message, **kwargs):
        self.log(logging.WARNING, message, **kwargs)

    def error(self, message, **kwargs):
        self.log(logging.ERROR, message, **kwargs)

    def critical(self, message, **kwargs):
        self.log(logging.CRITICAL, message, **kwargs)


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


# Make this accessible from the app_logger
app_logger.kv = KVLogger(app_logger)
app_logger.debug_mode = DebugMode(app_logger)
