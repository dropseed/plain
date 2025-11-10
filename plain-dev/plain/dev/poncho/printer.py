import re
from pathlib import Path
from typing import Any, NamedTuple


class Message(NamedTuple):
    type: str
    data: bytes | dict[str, Any] | str
    time: Any
    name: str | None
    color: str | None
    stream: str = "stdout"


class Printer:
    """
    Printer is where Poncho's user-visible output is defined. A Printer
    instance receives typed messages and prints them to its output (usually
    STDOUT) in the Poncho format.
    """

    def __init__(
        self,
        print_func: Any,
        time_format: str = "%H:%M:%S",
        width: int = 0,
        color: bool = True,
        prefix: bool = True,
        log_file: Path | str | None = None,
    ) -> None:
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

    def write(self, message: Message) -> None:
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
                prefix_base = f"{time_formatted} {name}"

                # Color the timestamp and name with process color
                if self.color and message.color:
                    prefix_base = _color_string(message.color, prefix_base)

                # Use fat red pipe for stderr, dim pipe for stdout
                if message.stream == "stderr" and self.color:
                    pipe = _color_string("31", "┃")
                elif self.color:
                    pipe = _color_string("2", "|")
                else:
                    pipe = "|"

                prefix = prefix_base + pipe + " "

            # Dim the line content for system messages (color="2")
            if self.color and message.color == "2":
                line = _color_string("2", line)

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

    def close(self) -> None:
        if self.log_file and hasattr(self.log_file, "close"):
            self.log_file.close()


def _color_string(color: str, s: str) -> str:
    def _ansi(code: str | int) -> str:
        return f"\033[{code}m"

    return f"{_ansi(0)}{_ansi(color)}{s}{_ansi(0)}"


# Regex that matches ANSI escape sequences (e.g. colour codes, cursor control
# sequences, etc.).  Adapted from ECMA-48 / VT100 patterns.
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
