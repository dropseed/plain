import plain.runtime

plain.runtime.setup()


def print_bold(s: str) -> None:
    print("\033[1m", end="")
    print(s)
    print("\033[0m", end="")


def print_italic(s: str) -> None:
    print("\x1b[3m", end="")
    print(s)
    print("\x1b[0m", end="")


def print_dim(s: str) -> None:
    print("\x1b[2m", end="")
    print(s)
    print("\x1b[0m", end="")


name = plain.runtime.settings.NAME
version = plain.runtime.settings.VERSION
width = len(name) + 1 + len(version) + 2  # space between + padding
line = "─" * width
print(f"\n╭{line}╮")
print(f"│ \033[1m{name}\033[0m \033[2m{version}\033[0m │")
print(f"╰{line}╯\n")

if shell_import := plain.runtime.settings.SHELL_IMPORT:
    from importlib import import_module

    print_bold(f"Importing {shell_import}...")
    module = import_module(shell_import)

    if module.__file__:
        with open(module.__file__) as f:
            contents = f.read()
            for line in contents.splitlines():
                print_dim(f"{line}")

        print()

    # Emulate `from module import *`
    names = getattr(
        module, "__all__", [name for name in dir(module) if not name.startswith("_")]
    )
    globals().update({name: getattr(module, name) for name in names})
else:
    print_italic("Use settings.SHELL_IMPORT to customize the shell startup.\n")
