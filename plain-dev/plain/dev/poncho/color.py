from collections.abc import Iterator

ANSI_COLOURS = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]

for i, name in enumerate(ANSI_COLOURS):
    globals()[name] = str(30 + i)
    globals()["intense_" + name] = str(30 + i) + ";1"


def get_colors() -> Iterator[str]:
    cs = [
        "cyan",
        "yellow",
        "green",
        "magenta",
        "blue",
        "intense_cyan",
        "intense_yellow",
        "intense_green",
        "intense_magenta",
        "intense_blue",
    ]
    cs = [globals()[c] for c in cs]

    i = 0
    while True:
        yield cs[i % len(cs)]
        i += 1
