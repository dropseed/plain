import sys
from collections import namedtuple

from .compat import ON_WINDOWS

Message = namedtuple("Message", "type data time name color")


class Printer:
    """
    Printer is where Poncho's user-visible output is defined. A Printer
    instance receives typed messages and prints them to its output (usually
    STDOUT) in the Poncho format.
    """

    def __init__(
        self,
        output=sys.stdout,
        time_format="%H:%M:%S",
        width=0,
        color=True,
        prefix=True,
    ):
        self.output = output
        self.time_format = time_format
        self.width = width
        self.color = color
        self.prefix = prefix

        try:
            # We only want to print colored messages if the given output supports
            # ANSI escape sequences. Usually, testing if it is a TTY is safe enough.
            self._colors_supported = self.output.isatty()
        except AttributeError:
            # If the given output does not implement isatty(), we assume that it
            # is not able to handle ANSI escape sequences.
            self._colors_supported = False

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
                if self.color and self._colors_supported and message.color:
                    prefix = _color_string(message.color, prefix)
            print(prefix + line, file=self.output, flush=True)


def _ansi(code):
    return f"\033[{code}m"


def _color_string(color, s):
    return f"{_ansi(0)}{_ansi(color)}{s}{_ansi(0)}"


if ON_WINDOWS:
    # The colorama package provides transparent support for ANSI color codes
    # on Win32 platforms. We try and import and configure that, but fall back
    # to no color if we fail.
    try:
        import colorama
    except ImportError:

        def _color_string(color, s):
            return s
    else:
        colorama.init()
