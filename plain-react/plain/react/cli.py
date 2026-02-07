from __future__ import annotations

import os
import shutil
import subprocess

import click

from plain.cli import register_cli

from .vite import (
    create_package_json,
    create_react_entrypoint,
    create_ssr_entrypoint,
    create_vite_config,
    get_package_json_path,
    get_react_root,
    get_vite_config_path,
)


@register_cli("react")
@click.group("react")
def cli() -> None:
    """React integration for Plain."""


@cli.command()
@click.option("--ssr", is_flag=True, help="Include SSR support (requires mini-racer)")
def init(ssr: bool) -> None:
    """Initialize a Plain React project with Vite, React, and example files."""
    root = get_react_root()

    # Create package.json if it doesn't exist
    if not os.path.exists(get_package_json_path()):
        create_package_json(root)
    else:
        click.secho("package.json already exists, skipping.", fg="yellow")

    # Create vite.config.js if it doesn't exist
    if not os.path.exists(get_vite_config_path()):
        create_vite_config(root)
    else:
        click.secho("vite.config.js already exists, skipping.", fg="yellow")

    # Create React entry point and example page
    react_dir = os.path.join(root, "app", "react")
    if not os.path.exists(react_dir):
        create_react_entrypoint(root)

        # Copy the plain-react client library
        client_src = os.path.join(
            os.path.dirname(__file__), "client", "plain-react.jsx"
        )
        client_dst = os.path.join(react_dir, "plain-react.jsx")
        shutil.copy2(client_src, client_dst)
        click.secho(f"Created {os.path.relpath(client_dst)}", fg="green")
    else:
        click.secho("app/react/ already exists, skipping.", fg="yellow")

    # Create SSR entry point if requested
    if ssr:
        ssr_path = os.path.join(root, "app", "react", "ssr.jsx")
        if not os.path.exists(ssr_path):
            create_ssr_entrypoint(root)
        else:
            click.secho("app/react/ssr.jsx already exists, skipping.", fg="yellow")

    # Install npm dependencies
    if shutil.which("npm"):
        click.secho("\nInstalling npm dependencies...", bold=True)
        subprocess.run(["npm", "install"], cwd=root, check=False)
        click.secho("Done!", fg="green")
    else:
        click.secho(
            "\nnpm not found. Run 'npm install' manually to install dependencies.",
            fg="yellow",
        )

    click.echo()
    click.secho("Plain React initialized!", bold=True, fg="green")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Add 'plain.react' to INSTALLED_PACKAGES in your settings")
    click.echo("  2. Add ReactMiddleware to your MIDDLEWARE:")
    click.echo('     "plain.react.middleware.ReactMiddleware"')
    click.echo("  3. Create a view:")
    click.echo()
    click.echo("     from plain.react.views import ReactView")
    click.echo()
    click.echo("     class IndexView(ReactView):")
    click.echo('         component = "Index"')
    if ssr:
        click.echo("         ssr = True")
    click.echo()
    click.echo("         def get_props(self):")
    click.echo('             return {"greeting": "Hello from Plain!"}')
    click.echo()
    click.echo("  4. Run 'plain dev' to start developing")
    if ssr:
        click.echo()
        click.echo("  SSR: Install mini-racer for server-side rendering:")
        click.echo("    uv add mini-racer")


@cli.command()
def build() -> None:
    """Build React assets for production."""
    from .vite import run_vite_build

    run_vite_build()
