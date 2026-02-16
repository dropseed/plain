import random
import re
import shutil
import subprocess
from pathlib import Path

import click

STARTER_REPOS = {
    "app": "https://github.com/dropseed/plain-starter-app",
    "bare": "https://github.com/dropseed/plain-starter-bare",
}

# Placeholder values used in the starter templates
TEMPLATE_CONTAINER_NAME = "app-postgres"
TEMPLATE_DB_PORT = "54321"


@click.command()
@click.argument("project_name")
@click.option(
    "--type",
    "starter_type",
    type=click.Choice(["app", "bare"]),
    default="app",
    help="Type of starter template to use",
)
@click.option(
    "--no-install",
    is_flag=True,
    help="Skip running ./scripts/install after setup",
)
def cli(project_name: str, starter_type: str, no_install: bool) -> None:
    """Bootstrap a new Plain project from starter templates"""
    project_path = Path.cwd() / project_name

    if project_path.exists():
        click.secho(
            f"Error: Directory '{project_name}' already exists", fg="red", err=True
        )
        raise click.Abort()

    # Clone the starter repository
    repo_url = STARTER_REPOS[starter_type]
    click.secho(f"Cloning {starter_type} starter template...", dim=True)

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, project_name],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        click.secho(
            f"Error cloning repository: {e.stderr.decode()}", fg="red", err=True
        )
        raise click.Abort()

    # Remove .git directory and reinitialize
    click.secho("Initializing new git repository...", dim=True)
    git_dir = project_path / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)

    subprocess.run(
        ["git", "init"],
        cwd=project_path,
        check=True,
        capture_output=True,
    )

    # Configure project-specific names and ports
    click.secho("Configuring project...", dim=True)
    db_port = str(random.randint(50000, 59999))

    pyproject_path = project_path / "pyproject.toml"
    if pyproject_path.exists():
        content = pyproject_path.read_text()
        content = re.sub(
            r'^name\s*=\s*["\'].*?["\']',
            f'name = "{project_name}"',
            content,
            count=1,
            flags=re.MULTILINE,
        )
        content = content.replace(TEMPLATE_CONTAINER_NAME, f"{project_name}-postgres")
        content = content.replace(TEMPLATE_DB_PORT, db_port)
        pyproject_path.write_text(content)

    for env_file in [project_path / ".env", project_path / ".env.example"]:
        if env_file.exists():
            content = env_file.read_text()
            content = content.replace(TEMPLATE_DB_PORT, db_port)
            env_file.write_text(content)

    # Run install script unless --no-install
    if not no_install:
        install_script = project_path / "scripts" / "install"
        if install_script.exists():
            click.echo(
                click.style("Running installation:", bold=True)
                + click.style(" ./scripts/install", dim=True)
            )
            try:
                subprocess.run(
                    ["./scripts/install"],
                    cwd=project_path,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                click.secho(
                    f"Warning: Installation script failed with exit code {e.returncode}",
                    fg="yellow",
                    err=True,
                )
                click.secho(
                    "You may need to run './scripts/install' manually.",
                    fg="yellow",
                    err=True,
                )

    # Success message
    click.echo()
    click.secho(
        f"✓ Project '{project_name}' created successfully!", fg="green", bold=True
    )
    click.echo()
    click.secho("Next steps:", bold=True)
    click.secho(f"  cd {project_name}")
    if no_install:
        click.secho("  ./scripts/install")
    click.secho("  uv run plain dev")
