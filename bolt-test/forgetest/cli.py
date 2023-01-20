import sys
import subprocess
import os

import click
from forgecore import Forge


@click.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cli(pytest_args):
    """Run tests with pytest"""
    forge = Forge()

    if forge.user_file_exists("settings.py"):
        # This is the somewhat non-standard Forge path for settings, which Pytest won't autodetect
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

    coverage_file = os.path.join(forge.forge_tmp_dir, ".coverage")

    # Turn deprecation warnings into errors
    if "-W" not in pytest_args:
        pytest_args = list(pytest_args)  # Make sure it's a list instead of tuple
        pytest_args.append("-W")
        pytest_args.append("error::DeprecationWarning")

    result = forge.venv_cmd(
        "coverage",
        "run",
        "-m",
        "pytest",
        *pytest_args,
        env={
            "PYTHONPATH": forge.project_dir,
            "COVERAGE_FILE": coverage_file,
        },
    )
    if result.returncode:
        # Can be invoked by pre-commit, so only exit if it fails
        sys.exit(result.returncode)

    if "GITHUB_STEP_SUMMARY" in os.environ:
        click.secho("Adding coverage report to GitHub Action summary", bold=True)
        subprocess.check_call(
            'echo "## Pytest coverage" >> $GITHUB_STEP_SUMMARY', shell=True
        )
        subprocess.check_call(
            "coverage report "
            + "--skip-empty "
            + "--format markdown "
            + f"--data-file {coverage_file} "
            + ">> $GITHUB_STEP_SUMMARY",
            shell=True,
        )

    html_result = forge.venv_cmd(
        "coverage",
        "html",
        "--skip-empty",
        "--directory",
        os.path.join(forge.forge_tmp_dir, "coverage"),
        env={
            "PYTHONPATH": forge.project_dir,
            "COVERAGE_FILE": coverage_file,
        },
    )
    if html_result.returncode:
        sys.exit(html_result.returncode)
