from .cli import compile


def run_dev_compile():
    compile(["--watch"])


def run_compile():
    compile([])
