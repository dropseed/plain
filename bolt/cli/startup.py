import bolt.runtime

bolt.runtime.setup()


def _print_bold(s):
    print("\033[1m", end="")
    print(s)
    print("\033[0m", end="")

def _print_italic(s):
    print("\x1B[3m", end="")
    print(s)
    print("\x1B[0m", end="")


_print_bold("\n⬣ Welcome to the Bolt shell! ⬣")

_app_shell = bolt.runtime.APP_PATH / "shell.py"

if _app_shell.exists():
    _print_bold("\nImporting custom app/shell.py")
    contents = _app_shell.read_text()

    for line in contents.splitlines():
        _print_italic(f">>> {line}")

    print()

    # Import * so we get everything that file imported
    # (which is mostly the point of having it)
    from app.shell import *  # noqa
