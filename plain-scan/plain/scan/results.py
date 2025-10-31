from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    """Result of a single security check."""

    name: str
    passed: bool
    message: str
    nested_checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
        }
        if self.nested_checks:
            result["nested_checks"] = [check.to_dict() for check in self.nested_checks]
        return result


@dataclass
class AuditResult:
    """Result of an audit of security checks."""

    name: str
    detected: bool
    checks: list[CheckResult] = field(default_factory=list)
    required: bool = True  # Whether this audit is required for all sites
    disabled: bool = False  # True if user disabled this audit via --disable
    description: str | None = None  # Optional description of what this audit checks

    @property
    def passed(self) -> bool:
        """Audit passes if detected and all checks pass, or if optional and not detected."""
        # Disabled audits are excluded from pass/fail logic
        if self.disabled:
            return True
        if not self.detected:
            # Optional audits pass even when not detected
            return not self.required
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "detected": self.detected,
            "required": self.required,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.disabled:
            result["disabled"] = self.disabled
        if self.description:
            result["description"] = self.description
        return result


@dataclass
class ScanResult:
    """Complete scan results for a URL."""

    url: str
    audits: list[AuditResult] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Scan passes if all audits pass (including required audits being detected)."""
        if not self.audits:
            return False
        return all(audit.passed for audit in self.audits)

    @property
    def passed_count(self) -> int:
        """Count of audits that passed (excluding disabled audits)."""
        return sum(1 for audit in self.audits if audit.passed and not audit.disabled)

    @property
    def failed_count(self) -> int:
        """Count of audits that failed (excluding disabled audits)."""
        return sum(
            1 for audit in self.audits if not audit.passed and not audit.disabled
        )

    @property
    def total_count(self) -> int:
        """Total count of audits (excluding disabled audits)."""
        return sum(1 for audit in self.audits if not audit.disabled)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "url": self.url,
            "passed": self.passed,
            "audits": [audit.to_dict() for audit in self.audits],
        }
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def to_markdown(self) -> str:
        """Convert scan results to markdown format."""
        lines = []

        # Header
        lines.append("# Plain Scan Results\n")
        lines.append(f"**URL:** {self.url}\n")

        # Overall status
        if self.passed:
            lines.append("✅ **All checks passed**\n")
        else:
            failed_count = sum(
                1 for audit in self.audits if not audit.passed and not audit.disabled
            )
            lines.append(
                f"❌ **{failed_count} check{'s' if failed_count != 1 else ''} failed**\n"
            )

        # Metadata
        if self.metadata:
            lines.append("## Response Details\n")
            lines.append(f"- **Final URL:** {self.metadata.get('final_url')}\n")
            lines.append(f"- **Status:** {self.metadata.get('status_code')}\n")

            redirect_chain = self.metadata.get("redirect_chain")
            if redirect_chain:
                lines.append("\n**Redirects:**\n")
                for i, redirect in enumerate(redirect_chain, 1):
                    lines.append(
                        f"{i}. {redirect['url']} → {redirect['status_code']}\n"
                    )
                lines.append(
                    f"{len(redirect_chain) + 1}. {self.metadata.get('final_url')} → {self.metadata.get('status_code')}\n"
                )

            headers = self.metadata.get("headers")
            if headers:
                lines.append("\n**Headers:**\n")
                for header, value in headers.items():
                    lines.append(f"- **{header}:** `{value}`\n")

            cookies = self.metadata.get("cookies")
            if cookies:
                lines.append("\n**Cookies:**\n")
                for cookie in cookies:
                    attrs = []
                    if cookie["secure"]:
                        attrs.append("Secure")
                    else:
                        attrs.append("Not Secure")
                    if cookie["httponly"]:
                        attrs.append("HttpOnly")
                    if cookie["samesite"]:
                        attrs.append(f"SameSite={cookie['samesite']}")
                    lines.append(f"- **{cookie['name']}:** {' · '.join(attrs)}\n")

        # Audits
        lines.append("\n## Security Checks\n")
        for audit in self.audits:
            if audit.detected:
                icon = "✅" if audit.passed else "❌"
                # Add "required" label only for required audits
                required_label = " *(required)*" if audit.required else ""
                lines.append(f"\n### {icon} {audit.name}{required_label}\n")

                for check in audit.checks:
                    check_icon = "✓" if check.passed else "✗"
                    lines.append(f"- {check_icon} **{check.name}:** {check.message}\n")

                    for nested in check.nested_checks:
                        nested_icon = "✓" if nested.passed else "✗"
                        lines.append(f"  - {nested_icon} {nested.message}\n")
            else:
                # Security feature not detected - check if user disabled or just not found
                if audit.disabled:
                    lines.append(f"\n### ⚪ {audit.name}\n")
                    lines.append("*Disabled*\n")
                elif audit.required:
                    lines.append(f"\n### ❌ {audit.name}\n")
                    lines.append("*Required, not detected*\n")
                else:
                    lines.append(f"\n### ⚪ {audit.name}\n")
                    lines.append("*Not detected*\n")

        return "\n".join(lines)
