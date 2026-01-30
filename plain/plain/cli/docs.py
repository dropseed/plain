from __future__ import annotations

import importlib.util
from pathlib import Path

import click

from .llmdocs import LLMDocs

# All known official Plain packages: pip name -> short description
KNOWN_PACKAGES = {
    "plain": "Web framework core",
    "plain-admin": "Backend admin interface",
    "plain-api": "Class-based API views",
    "plain-auth": "User authentication and authorization",
    "plain-cache": "Database-backed cache with optional expiration",
    "plain-code": "Preconfigured code formatting and linting",
    "plain-dev": "Local development server with auto-reload",
    "plain-elements": "HTML template components",
    "plain-email": "Send email",
    "plain-esbuild": "Build JavaScript with esbuild",
    "plain-flags": "Feature flags via database models",
    "plain-htmx": "HTMX integration for templates and views",
    "plain-jobs": "Background jobs with a database-driven queue",
    "plain-loginlink": "Link-based authentication",
    "plain-models": "Model data and store it in a database",
    "plain-oauth": "OAuth provider login",
    "plain-observer": "On-page telemetry and observability",
    "plain-pages": "Serve static pages, markdown, and assets",
    "plain-pageviews": "Client-side pageview tracking",
    "plain-passwords": "Password authentication",
    "plain-pytest": "Test with pytest",
    "plain-redirection": "URL redirection with admin and logging",
    "plain-scan": "Test for production best practices",
    "plain-sessions": "Database-backed sessions",
    "plain-start": "Bootstrap a new project from templates",
    "plain-support": "Support forms for your application",
    "plain-tailwind": "Tailwind CSS without JavaScript or npm",
    "plain-toolbar": "Debug toolbar",
    "plain-tunnel": "Remote access to local dev server",
    "plain-vendor": "Vendor CDN scripts and styles",
}


def _normalize_module(module: str) -> str:
    """Normalize a module string to dotted form (e.g. plain-models -> plain.models)."""
    module = module.replace("-", ".")
    if not module.startswith("plain"):
        module = f"plain.{module}"
    return module


def _pip_package_name(module: str) -> str:
    """Convert a dotted module name to a pip package name (e.g. plain.models -> plain-models)."""
    return module.replace(".", "-")


def _is_installed(module: str) -> bool:
    """Check if a dotted module name is installed."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _online_docs_url(pip_name: str) -> str:
    """Return the online documentation URL for a package."""
    module = pip_name.replace("-", ".")
    return f"https://plainframework.com/docs/{pip_name}/{module.replace('.', '/')}/"


@click.command()
@click.option("--symbols", is_flag=True, help="Show symbolicated API surface only")
@click.option("--list", "show_list", is_flag=True, help="List available packages")
@click.argument("module", default="")
def docs(module: str, symbols: bool, show_list: bool) -> None:
    """Show documentation for a package"""
    if show_list:
        for pip_name in sorted(KNOWN_PACKAGES):
            description = KNOWN_PACKAGES[pip_name]
            dotted = pip_name.replace("-", ".")
            installed = _is_installed(dotted)
            status = " (installed)" if installed else ""
            click.echo(f"  {pip_name}{status} — {description}")
        return

    if not module:
        raise click.UsageError(
            "You must specify a module. Use --list to see available packages."
        )

    module = _normalize_module(module)

    # Get the module path
    spec = importlib.util.find_spec(module)
    if not spec or not spec.origin:
        pip_name = _pip_package_name(module)
        if pip_name in KNOWN_PACKAGES:
            msg = (
                f"{module} is not installed.\n\n"
                f"  Online docs:  {_online_docs_url(pip_name)}"
            )
        else:
            msg = f"Module {module} not found. Use --list to see available packages."
        raise click.UsageError(msg)

    module_path = Path(spec.origin).parent

    llm_docs = LLMDocs([module_path])
    llm_docs.load()
    llm_docs.print(
        relative_to=module_path.parent,
        include_docs=not symbols,
        include_symbols=symbols,
    )
