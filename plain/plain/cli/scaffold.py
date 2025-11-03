from pathlib import Path

import click

import plain.runtime


@click.command()
@click.argument("package_name")
def create(package_name: str) -> None:
    """Create a new local package"""
    package_dir = plain.runtime.APP_PATH / package_name
    package_dir.mkdir(exist_ok=True)

    empty_dirs = (
        f"templates/{package_name}",
        "migrations",
    )
    for d in empty_dirs:
        (package_dir / d).mkdir(parents=True, exist_ok=True)

    empty_files = (
        "__init__.py",
        "migrations/__init__.py",
        "models.py",
        "views.py",
    )
    for f in empty_files:
        (package_dir / f).touch(exist_ok=True)

    # Create a urls.py file with a default namespace
    if not (package_dir / "urls.py").exists():
        (package_dir / "urls.py").write_text(
            f"""from plain.urls import path, Router

from . import views


class {package_name.capitalize()}Router(Router):
    namespace = f"{package_name}"
    urls = [
        # path("", views.IndexView, name="index"),
    ]
"""
        )

    click.secho(
        f'Created {package_dir.relative_to(Path.cwd())}. Make sure to add "app.{package_name}" to INSTALLED_PACKAGES!',
        fg="green",
    )
