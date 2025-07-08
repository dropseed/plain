import re
from collections import namedtuple
from pathlib import Path

Message = namedtuple("Message", "type data time name color")


class Printer:
    """
    Printer is where Poncho's user-visible output is defined. A Printer
    instance receives typed messages and prints them to its output (usually
    STDOUT) in the Poncho format.
    """

    def __init__(
        self,
        print_func,
        time_format="%H:%M:%S",
        width=0,
        color=True,
        prefix=True,
        log_file=None,
    ):
        self.print_func = print_func
        self.time_format = time_format
        self.width = width
        self.color = color
        self.prefix = prefix
        if log_file is not None:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = log_path.open("w", encoding="utf-8")
        else:
            self.log_file = None

    def write(self, message):
        if message.type != "line":
            raise RuntimeError('Printer can only process messages of type "line"')

        name = message.name if message.name is not None else ""
        name = name.ljust(self.width)
        if name:
            name += " "

        # When encountering data that cannot be interpreted as UTF-8 encoded
        # Unicode, Printer will replace the unrecognisable bytes with the
        # Unicode replacement character (U+FFFD).
        if isinstance(message.data, bytes):
            string = message.data.decode("utf-8", "replace")
        else:
            string = message.data

        for line in string.splitlines():
            prefix = ""
            if self.prefix:
                time_formatted = message.time.strftime(self.time_format)
                prefix = f"{time_formatted} {name}| "
                if self.color and message.color:
                    prefix = _color_string(message.color, prefix)

            formatted = prefix + line

            # Send original (possibly ANSI-coloured) string to stdout.
            self.print_func(formatted)

            # Strip ANSI escape sequences before persisting to disk so the log
            # file contains plain text only.  This avoids leftover control
            # codes (e.g. hidden-cursor) that can confuse terminals when the
            # log is displayed later via `plain dev logs`.
            if self.log_file is not None:
                plain = _ANSI_RE.sub("", formatted)
                self.log_file.write(plain + "\n")
                self.log_file.flush()

    def close(self):
        if self.log_file and hasattr(self.log_file, "close"):
            self.log_file.close()


def _color_string(color, s):
    def _ansi(code):
        return f"\033[{code}m"

    return f"{_ansi(0)}{_ansi(color)}{s}{_ansi(0)}"


# Regex that matches ANSI escape sequences (e.g. colour codes, cursor control
# sequences, etc.).  Adapted from ECMA-48 / VT100 patterns.
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
