from .cli import compile


def run_dev_compile():
    # This will run by itself as a command, so it can exit()
    compile(["--watch"], standalone_mode=True)


def run_compile():
    # Standalone mode prevents it from exit()ing
    compile([], standalone_mode=False)
