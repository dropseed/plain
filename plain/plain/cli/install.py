import subprocess
import sys

import click

from .agent.prompt import prompt_agent


@click.command()
@click.argument("packages", nargs=-1, required=True)
@click.option(
    "--agent-command",
    envvar="PLAIN_AGENT_COMMAND",
    help="Run command with generated prompt",
)
@click.option(
    "--print",
    "print_only",
    is_flag=True,
    help="Print the prompt without running the agent",
)
def install(
    packages: tuple[str, ...],
    agent_command: str | None = None,
    print_only: bool = False,
) -> None:
    """Install Plain packages with agent assistance"""
    # Validate all package names
    invalid_packages = [pkg for pkg in packages if not pkg.startswith("plain")]
    if invalid_packages:
        raise click.UsageError(
            f"The following packages do not start with 'plain': {', '.join(invalid_packages)}\n"
            "This command is only for Plain framework packages."
        )

    # Install all packages first
    if len(packages) == 1:
        click.secho(f"Installing {packages[0]}...", bold=True, err=True)
    else:
        click.secho(f"Installing {len(packages)} packages...", bold=True, err=True)
        for pkg in packages:
            click.secho(f"  - {pkg}", err=True)
        click.echo(err=True)

    install_cmd = ["uv", "add"] + list(packages)
    result = subprocess.run(install_cmd, check=False, stderr=sys.stderr)

    if result.returncode != 0:
        raise click.ClickException("Failed to install packages")

    click.echo(err=True)
    if len(packages) == 1:
        click.secho(f"✓ {packages[0]} installed successfully", fg="green", err=True)
    else:
        click.secho(
            f"✓ {len(packages)} packages installed successfully", fg="green", err=True
        )
    click.echo(err=True)

    # Build the prompt for the agent to complete setup
    lines = [
        f"Complete the setup for the following Plain packages that were just installed: {', '.join(packages)}",
        "",
        "## Instructions",
        "",
        "For each package:",
        "1. Run `uv run plain docs <package>` and read the installation instructions",
        "2. If the docs point out that it is a --dev tool, move it to the dev dependencies in pyproject.toml: `uv remove <package> && uv add <package> --dev`",
        "3. Go through the installation instructions and complete any code modifications that are needed",
        "",
        "DO NOT commit any changes",
        "",
        "Report back with:",
        "- Whether the setup completed successfully",
        "- Any manual steps that the user will need to complete",
        "- Any issues or errors encountered",
    ]

    prompt = "\n".join(lines)
    success = prompt_agent(prompt, agent_command, print_only)
    if not success:
        raise click.Abort()
