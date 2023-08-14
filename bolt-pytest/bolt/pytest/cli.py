import sys
import subprocess
import os

import click


@click.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cli(pytest_args):
    """Run tests with pytest"""

    try:
        repo_root = (
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError:
        click.secho("All bolt projects are expected to be in a git repo and we couldn't find one.", fg="red")
        sys.exit(1)

    bolt_tmp_dir = os.path.join(repo_root, ".bolt")
    if not os.path.exists(os.path.join(bolt_tmp_dir, ".gitignore")):
        os.makedirs(bolt_tmp_dir, exist_ok=True)
        with open(os.path.join(bolt_tmp_dir, ".gitignore"), "w") as f:
            f.write("*\n")

    bolt_app_dir = os.path.join(repo_root, "app")

    coverage_file = os.path.join(bolt_tmp_dir, ".coverage")

    # Turn deprecation warnings into errors
#     if "-W" not in pytest_args:
#         pytest_args = list(pytest_args)  # Make sure it's a list instead of tuple
#         pytest_args.append("-W")
#         pytest_args.append("error::DeprecationWarning")

    click.secho("Running bolt compile", bold=True)
    result = subprocess.run(["bolt", "compile"])
    if result.returncode:
        sys.exit(result.returncode)

    print()

    click.secho("Running pytest with coverage", bold=True)
    result = subprocess.run([
            "coverage",
            "run",
            "-m",
            "pytest",
            *pytest_args,
        ],
        env={
            **os.environ,
            "APP_ENV": "test",
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

    html_result = subprocess.run([
            "coverage",
            "html",
            "--skip-empty",
            "--directory",
            os.path.join(bolt_tmp_dir, "coverage"),
        ],
        env={
            **os.environ,
            "COVERAGE_FILE": coverage_file,
        },
    )
    if html_result.returncode:
        sys.exit(html_result.returncode)
