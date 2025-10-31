from __future__ import annotations

import click

from .metadata import ScanMetadata
from .results import CheckResult, ScanResult


def format_check_result(check: CheckResult, indent: int = 0) -> list[str]:
    """Format a single check result with nested checks."""
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
    return [line]


def format_verbose_metadata(metadata: ScanMetadata | None) -> str:
    """Format metadata for verbose output."""
    lines = []

    # Response chain
    if not metadata or not metadata.responses:
        return ""

    lines.append(click.style("Response Chain:", bold=True))
    lines.append("")

    # Display each response in the chain
    for i, response_data in enumerate(metadata.responses, 1):
        is_final = i == len(metadata.responses)
        is_redirect = not is_final

        # Response header
        if is_redirect:
            lines.append(
                click.style(
                    f"Response {i} (Redirect): {response_data.url} → {response_data.status_code}",
                    bold=True,
                )
            )
        else:
            lines.append(
                click.style(
                    f"Response {i} (Final): {response_data.url} → {response_data.status_code}",
                    bold=True,
                )
            )
        lines.append("")

        # Headers
        if response_data.headers:
            lines.append("  Headers:")
            for header, value in response_data.headers.items():
                # Show full header values with bold+dim header name and dim value
                header_line = (
                    "    "
                    + click.style(header, bold=True, dim=True)
                    + click.style(": ", dim=True)
                    + click.style(value, dim=True)
                )
                lines.append(header_line)
            lines.append("")

        # Cookies
        if response_data.cookies:
            lines.append("  Cookies:")
            for cookie in response_data.cookies:
                attrs = []
                if cookie.secure:
                    attrs.append(click.style("Secure", fg="green"))
                else:
                    attrs.append(click.style("Not Secure", fg="red"))
                if cookie.httponly:
                    attrs.append(click.style("HttpOnly", fg="green"))
                if cookie.samesite:
                    attrs.append(click.style(f"SameSite={cookie.samesite}", fg="green"))

                lines.append(f"    {cookie.name}: {' · '.join(attrs)}")
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
                lines.append(
                    "  " + click.style(audit.description, dim=True, italic=True)
                )

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

    # Overall result - white text on colored background
    # Count audits (excluding disabled ones)
    active_audits = [audit for audit in scan_result.audits if not audit.disabled]
    passed_audits = [audit for audit in active_audits if audit.passed]

    if scan_result.passed:
        overall = click.style(
            f" ✔ {len(passed_audits)}/{len(active_audits)} audits passed ",
            fg="white",
            bg="green",
            bold=True,
        )
    else:
        overall = click.style(
            f" ✗ {len(passed_audits)}/{len(active_audits)} audits passed ",
            fg="white",
            bg="red",
            bold=True,
        )
    lines.append(overall)

    return "\n".join(lines)


def to_markdown(scan_result: ScanResult, verbose: bool = False) -> str:
    """Convert scan results to markdown format."""
    lines = []

    # Header
    lines.append("# Plain Scan Results\n")
    lines.append(f"**URL:** {scan_result.url}\n")

    # Overall status
    # Count audits (excluding disabled ones)
    active_audits = [audit for audit in scan_result.audits if not audit.disabled]
    passed_audits = [audit for audit in active_audits if audit.passed]

    if scan_result.passed:
        lines.append(
            f"✅ **{len(passed_audits)}/{len(active_audits)} audits passed**\n"
        )
    else:
        lines.append(
            f"❌ **{len(passed_audits)}/{len(active_audits)} audits passed**\n"
        )

    # Metadata - Response Chain (only in verbose mode)
    if verbose and scan_result.metadata and scan_result.metadata.responses:
        lines.append("## Response Chain\n")

        # Display each response
        for i, response_data in enumerate(scan_result.metadata.responses, 1):
            is_final = i == len(scan_result.metadata.responses)
            is_redirect = not is_final

            # Response header
            if is_redirect:
                lines.append(
                    f"### Response {i} (Redirect)\n\n"
                    f"- **URL:** {response_data.url}\n"
                    f"- **Status:** {response_data.status_code}\n"
                )
            else:
                lines.append(
                    f"### Response {i} (Final)\n\n"
                    f"- **URL:** {response_data.url}\n"
                    f"- **Status:** {response_data.status_code}\n"
                )

            # Headers
            if response_data.headers:
                lines.append("\n**Headers:**\n")
                for header, value in response_data.headers.items():
                    lines.append(f"- `{header}`: `{value}`")

            # Cookies
            if response_data.cookies:
                lines.append("\n**Cookies:**\n")
                for cookie in response_data.cookies:
                    attrs = []
                    if cookie.secure:
                        attrs.append("Secure")
                    else:
                        attrs.append("Not Secure")
                    if cookie.httponly:
                        attrs.append("HttpOnly")
                    if cookie.samesite:
                        attrs.append(f"SameSite={cookie.samesite}")
                    lines.append(f"- **{cookie.name}:** {' · '.join(attrs)}")

            lines.append("\n")

    # Audits
    lines.append("\n## Audits\n")
    for audit in scan_result.audits:
        if audit.detected:
            icon = "✅" if audit.passed else "❌"
            # Add "required" label only for required audits
            required_label = " *(required)*" if audit.required else ""
            lines.append(f"\n### {icon} {audit.name}{required_label}\n")

            # Show description in verbose mode
            if verbose and audit.description:
                lines.append(f"*{audit.description}*\n")

            for check in audit.checks:
                check_icon = "✓" if check.passed else "✗"
                lines.append(f"- {check_icon} **{check.name}:** {check.message}")
        else:
            # Security feature not detected - check if user disabled or just not found
            if audit.disabled:
                lines.append(f"\n### ⚪ {audit.name}\n")
                lines.append("*Disabled*")
            elif audit.required:
                lines.append(f"\n### ❌ {audit.name}\n")
                lines.append("*Required, not detected*")
            else:
                lines.append(f"\n### ⚪ {audit.name}\n")
                lines.append("*Not detected*")

    return "\n".join(lines)
