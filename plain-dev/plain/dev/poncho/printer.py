from collections import namedtuple

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
    ):
        self.print_func = print_func
        self.time_format = time_format
        self.width = width
        self.color = color
        self.prefix = prefix

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

            self.print_func(prefix + line)


def _color_string(color, s):
    def _ansi(code):
        return f"\033[{code}m"

    return f"{_ansi(0)}{_ansi(color)}{s}{_ansi(0)}"
