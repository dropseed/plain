import contextlib
import os
import subprocess
import sys

import click

from bolt.runtime import settings

try:
    from bolt.dev.services import Services
except ImportError:
    Services = None


@click.command(
    context_settings={
        "ignore_unknown_options": True,
    }
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cli(pytest_args):
    """Run tests with pytest"""

    bolt_tmp_dir = str(settings.BOLT_TEMP_PATH)

    if not os.path.exists(os.path.join(bolt_tmp_dir, ".gitignore")):
        os.makedirs(bolt_tmp_dir, exist_ok=True)
        with open(os.path.join(bolt_tmp_dir, ".gitignore"), "w") as f:
            f.write("*\n")

    # Turn deprecation warnings into errors
    #     if "-W" not in pytest_args:
    #         pytest_args = list(pytest_args)  # Make sure it's a list instead of tuple
    #         pytest_args.append("-W")
    #         pytest_args.append("error::DeprecationWarning")

    os.environ.setdefault("APP_ENV", "test")

    click.secho(f"Running pytest with APP_ENV={os.environ['APP_ENV']}", bold=True)

    # Won't want to start services automatically in some cases...
    # may need a better check for this but CI is the primary auto-exclusion
    services = (
        Services() if "CI" not in os.environ and Services else contextlib.nullcontext()
    )
    with services:
        result = subprocess.run(
            [
                "pytest",
                *pytest_args,
            ],
            env={
                **os.environ,
            },
        )

    if result.returncode:
        # Can be invoked by pre-commit, so only exit if it fails
        sys.exit(result.returncode)
