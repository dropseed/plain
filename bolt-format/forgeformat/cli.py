import os

import click
from forgecore import Forge


@click.command("format")  # format is a keyword
@click.option("--check", is_flag=True)
@click.option("--black", is_flag=True, default=True)
@click.option("--isort", is_flag=True, default=True)
def cli(check, black, isort):
    """Format Python code with black and isort"""
    forge = Forge()

    # Make relative for nicer output
    target = os.path.relpath(forge.project_dir)

    if black:
        click.secho("Formatting with black", bold=True)
        black_args = ["--extend-exclude", "migrations"]
        if check:
            black_args.append("--check")
        black_args.append(target)
        forge.venv_cmd(
            "black",
            *black_args,
            check=True,
        )

    if black and isort:
        click.echo()

    if isort:
        click.secho("Formatting with isort", bold=True)
        isort_config_root = os.path.join(os.path.dirname(__file__), "forge_isort.cfg")

        # Include --src so internal imports are recognized correctly
        isort_args = ["--settings-file", isort_config_root, "--src", target]
        if check:
            isort_args.append("--check")
        isort_args.append(target)
        forge.venv_cmd("isort", *isort_args, check=True)


if __name__ == "__main__":
    cli()
