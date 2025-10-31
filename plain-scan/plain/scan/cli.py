from __future__ import annotations

import json
import sys

import click

from plain.cli import register_cli
from plain.cli.runtime import without_runtime_setup

from .results import CheckResult, ScanResult
from .scanner import Scanner


def normalize_url(url: str) -> str:
    """Normalize URL by adding https:// scheme if missing."""
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def format_check_result(check: CheckResult, indent: int = 0) -> list[str]:
    """Format a single check result for human-readable output."""
    prefix = "  " * indent
    icon = "✓" if check.passed else "✗"
    icon_color = "green" if check.passed else "red"

    # Icon is colored, name is bold, message is dim
    line = (
        f"{prefix}"
        + click.style(icon, fg=icon_color)
        + " "
        + click.style(check.name, bold=True)
        + ": "
        + click.style(check.message, dim=True)
    )
    lines = [line]

    # Add nested checks
    for nested_check in check.nested_checks:
        lines.extend(format_check_result(nested_check, indent + 1))

    return lines


def format_verbose_metadata(metadata: dict) -> str:
    """Format metadata for verbose output."""
    lines = []

    # Request chain
    lines.append(click.style("Request Information:", bold=True))
    lines.append("")

    if metadata.get("redirect_chain"):
        lines.append("Redirect chain:")
        for i, redirect in enumerate(metadata["redirect_chain"], 1):
            lines.append(f"  {i}. {redirect['url']} → {redirect['status_code']}")
        lines.append(
            f"  {len(metadata['redirect_chain']) + 1}. {metadata['final_url']} → {metadata['status_code']}"
        )
    else:
        lines.append(f"Final URL: {metadata['final_url']} ({metadata['status_code']})")

    lines.append("")

    # Security headers
    if metadata.get("headers"):
        lines.append(click.style("Security Headers:", bold=True))
        lines.append("")
        for header, value in metadata["headers"].items():
            # Truncate long headers for readability
            display_value = value if len(value) <= 100 else value[:97] + "..."
            lines.append(f"  {header}: {display_value}")
        lines.append("")

    # Cookies
    if metadata.get("cookies"):
        lines.append(click.style("Cookies:", bold=True))
        lines.append("")
        for cookie in metadata["cookies"]:
            attrs = []
            if cookie["secure"]:
                attrs.append(click.style("Secure", fg="green"))
            else:
                attrs.append(click.style("Not Secure", fg="red"))
            if cookie["httponly"]:
                attrs.append(click.style("HttpOnly", fg="green"))
            if cookie["samesite"]:
                attrs.append(click.style(f"SameSite={cookie['samesite']}", fg="green"))

            lines.append(f"  {cookie['name']}: {' · '.join(attrs)}")
        lines.append("")

    return "\n".join(lines)


def format_human_readable(scan_result: ScanResult, verbose: bool = False) -> str:
    """Format scan results for human-readable output."""
    lines = []

    # Verbose metadata first
    if verbose and scan_result.metadata:
        lines.append(format_verbose_metadata(scan_result.metadata))

    # Scan results
    lines.append(click.style(f"Scan Results for: {scan_result.url}", bold=True))
    lines.append("")

    if not scan_result.audits:
        lines.append(click.style("No audits to check (all disabled)", fg="yellow"))
        lines.append("")
        return "\n".join(lines)

    for audit in scan_result.audits:
        # Audit header
        if audit.detected:
            icon = "✓" if audit.passed else "✗"
            icon_color = "green" if audit.passed else "red"
            # Icon is colored, audit name is bold
            audit_line = (
                click.style(icon, fg=icon_color)
                + " "
                + click.style(audit.name, bold=True)
            )
            # Add "required" badge only for required audits
            if audit.required:
                audit_line += " " + click.style("(required)", fg="yellow", dim=True)
            lines.append(audit_line)

            # Show description in verbose mode
            if verbose and audit.description:
                lines.append("  " + click.style(audit.description, dim=True))

            # Audit checks
            for check in audit.checks:
                lines.extend(format_check_result(check, indent=1))
        else:
            # Security feature not detected - check if user disabled or just not found
            if audit.disabled:
                # User disabled via --disable flag
                audit_line = (
                    click.style("○", fg="bright_black")
                    + " "
                    + click.style(audit.name, bold=True)
                    + " "
                    + click.style("(disabled)", dim=True)
                )
                lines.append(audit_line)
            elif audit.required:
                # Required but not detected - show as failed
                audit_line = (
                    click.style("✗", fg="red")
                    + " "
                    + click.style(audit.name, bold=True)
                    + " "
                    + click.style("(required, not detected)", dim=True)
                )
                lines.append(audit_line)
            else:
                # Not detected optional audit - show without "optional" label
                audit_line = (
                    click.style("○", fg="yellow")
                    + " "
                    + click.style(audit.name, bold=True)
                    + " "
                    + click.style("(not detected)", dim=True)
                )
                lines.append(audit_line)

        lines.append("")  # Blank line between audits

    # Overall result - icon is colored, text uses bold/dim
    if scan_result.passed:
        overall = (
            click.style("✔", fg="green")
            + " "
            + click.style("All checks passed", bold=True)
        )
    else:
        # Count failed checks (excluding disabled audits)
        failed_count = sum(
            1 for audit in scan_result.audits if not audit.passed and not audit.disabled
        )
        check_word = "check" if failed_count == 1 else "checks"
        overall = (
            click.style("✗", fg="red")
            + " "
            + click.style(f"{failed_count} {check_word} failed", bold=True)
        )
    lines.append(overall)

    return "\n".join(lines)


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
    """Scan a URL for HTTP security configuration issues."""

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
        click.echo(result.to_markdown())
    elif format == "cli":
        click.echo(format_human_readable(result, verbose=verbose))

    # Exit with error code if scan failed (but not if all audits were ignored)
    if not result.passed and result.audits:
        sys.exit(1)
