import subprocess
import sys

import click


@click.command()
@click.argument("packages", nargs=-1, required=True)
def install(packages: tuple[str, ...]) -> None:
    """Install Plain packages"""
    # Validate all package names
    invalid_packages = [pkg for pkg in packages if not pkg.startswith("plain")]
    if invalid_packages:
        raise click.UsageError(
            f"The following packages do not start with 'plain': {', '.join(invalid_packages)}\n"
            "This command is only for Plain framework packages."
        )

    # Install all packages
    if len(packages) == 1:
        click.secho(f"Installing {packages[0]}...", bold=True)
    else:
        click.secho(f"Installing {len(packages)} packages...", bold=True)
        for pkg in packages:
            click.secho(f"  - {pkg}")
        click.echo()

    install_cmd = ["uv", "add"] + list(packages)
    result = subprocess.run(install_cmd, check=False, stderr=sys.stderr)

    if result.returncode != 0:
        raise click.ClickException("Failed to install packages")

    click.echo()
    if len(packages) == 1:
        click.secho(f"{packages[0]} installed successfully", fg="green")
    else:
        click.secho(f"{len(packages)} packages installed successfully", fg="green")
