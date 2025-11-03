from __future__ import annotations

import json
import sys

import click

from plain.cli import register_cli
from plain.cli.runtime import without_runtime_setup

from .output import format_human_readable, to_markdown
from .scanner import Scanner


def normalize_url(url: str) -> str:
    """Normalize URL by adding https:// scheme if missing."""
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


@without_runtime_setup
@register_cli("scan")
@click.command()
@click.argument("url")
@click.option(
    "--format",
    type=click.Choice(["cli", "json", "markdown"]),
    default="cli",
    help="Output format (default: cli)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed request information and headers",
)
@click.option(
    "--disable",
    "-d",
    multiple=True,
    type=click.Choice(
        [
            "csp",
            "hsts",
            "redirects",
            "content-type-options",
            "frame-options",
            "referrer-policy",
            "cookies",
            "cors",
            "tls",
        ],
        case_sensitive=False,
    ),
    help="Disable specific security audits (can be used multiple times)",
)
def cli(
    url: str,
    format: str,
    verbose: bool,
    disable: tuple[str, ...],
) -> None:
    """Scan URL for security issues"""

    # Normalize URL (add https:// if no scheme provided)
    url = normalize_url(url)

    # Build list of disabled audits (using slugs)
    disabled = {slug.lower() for slug in disable}

    # Create scanner and run checks
    scanner = Scanner(url, disabled_audits=disabled)

    # Run scan
    try:
        result = scanner.scan()
    except Exception as e:
        click.secho(f"Error scanning {url}: {e}", fg="red", err=True)
        sys.exit(1)

    # Output results
    if format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    elif format == "markdown":
        click.echo(to_markdown(result, verbose=verbose))
    elif format == "cli":
        click.echo(format_human_readable(result, verbose=verbose))

    # Exit with error code if scan failed (but not if all audits were ignored)
    if not result.passed and result.audits:
        sys.exit(1)
