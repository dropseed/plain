import os
import subprocess
import sys

import click


@click.command()
@click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)
def shell(interface):
    """
    Runs a Python interactive interpreter. Tries to use IPython or
    bpython, if one of them is available.
    """

    if interface:
        interface = [interface]
    else:

        def get_default_interface():
            try:
                import IPython  # noqa

                return ["python", "-m", "IPython"]
            except ImportError:
                pass

            return ["python"]

        interface = get_default_interface()

    result = subprocess.run(
        interface,
        env={
            "PYTHONSTARTUP": os.path.join(os.path.dirname(__file__), "startup.py"),
            **os.environ,
        },
    )
    if result.returncode:
        sys.exit(result.returncode)


@click.command()
@click.argument("script", nargs=1, type=click.Path(exists=True))
def run(script):
    """Run a Python script in the context of your app"""
    before_script = "import plain.runtime; plain.runtime.setup()"
    command = f"{before_script}; exec(open('{script}').read())"
    result = subprocess.run(["python", "-c", command])
    if result.returncode:
        sys.exit(result.returncode)
