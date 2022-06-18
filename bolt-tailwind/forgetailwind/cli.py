import os
import subprocess

import click
from forgecore import Forge

from .core import Tailwind


@click.group("tailwind")
def cli():
    """Built-in Tailwind CSS commands"""
    pass


@cli.command()
@click.option("--watch", is_flag=True)
@click.option("--minify", is_flag=True)
def compile(watch, minify):
    forge = Forge()
    tailwind = Tailwind(forge.forge_tmp_dir)

    if not tailwind.is_installed() or tailwind.needs_update():
        version_to_install = tailwind.get_version_from_config()
        if version_to_install:
            click.secho(
                f"Installing Tailwind standalone {version_to_install}...", bold=True
            )
            version = tailwind.install(version_to_install)
        else:
            click.secho("Installing Tailwind standalone...", bold=True)
            version = tailwind.install()
        click.secho(f"Tailwind {version} installed", fg="green")

    args = [tailwind.standalone_path]

    args.append("-i")
    args.append(os.path.join(forge.project_dir, "static", "src", "tailwind.css"))

    args.append("-o")
    args.append(os.path.join(forge.project_dir, "static", "dist", "tailwind.css"))

    # These paths should actually work on Windows too
    # https://github.com/mrmlnc/fast-glob#how-to-write-patterns-on-windows
    args.append("--content")
    args.append(
        ",".join(
            [
                "./app/**/*.{html,js}",
                "./{.venv,.heroku/python}/lib/python*/site-packages/forge*/**/*.{html,js}",
            ]
        )
    )

    if watch:
        args.append("--watch")

    if minify:
        args.append("--minify")

    subprocess.check_call(args, cwd=os.path.dirname(forge.project_dir))


@cli.command()
def update():
    forge = Forge()
    tailwind = Tailwind(forge.forge_tmp_dir)
    click.secho("Installing Tailwind standalone...", bold=True)
    version = tailwind.install()
    click.secho(f"Tailwind {version} installed", fg="green")


if __name__ == "__main__":
    cli()
