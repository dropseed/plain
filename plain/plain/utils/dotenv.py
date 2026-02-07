"""
Custom .env file parser targeting bash `source` compatibility.

Supports:
- KEY=value (basic unquoted)
- KEY="double quoted value" (with escape handling and multiline)
- KEY='single quoted value' (literal, including multiline)
- export KEY=value (strips export prefix)
- Comments (# comment and inline KEY=value # comment)
- Variable expansion: $VAR and ${VAR} (in unquoted and double-quoted values)
- Command substitution: $(command)
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

__all__ = ["load_dotenv", "parse_dotenv"]

# Match ${VAR} or $VAR (VAR must start with letter/underscore, then alphanumeric/underscore)
_VAR_BRACE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_VAR_BARE_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
# Placeholder for escaped $ (to prevent expansion)
_ESCAPED_DOLLAR = "\x00DOLLAR\x00"


def load_dotenv(
    filepath: str | Path,
    *,
    override: bool = False,
) -> bool:
    """
    Load environment variables from a .env file into os.environ.

    Args:
        filepath: Path to the .env file
        override: If True, overwrite existing environment variables

    Returns:
        True if the file was loaded, False if it doesn't exist
    """
    path = Path(filepath)
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")

    # Skip command execution for keys that already exist (unless override)
    skip_commands_for = None if override else set(os.environ.keys())

    def on_bind(key: str, value: str) -> None:
        if override or key not in os.environ:
            os.environ[key] = value

    _parse_content(content, skip_commands_for=skip_commands_for, on_bind=on_bind)
    return True


def parse_dotenv(filepath: str | Path) -> dict[str, str]:
    """
    Parse a .env file and return a dictionary of key-value pairs.

    Does not modify os.environ. Supports multiline values in quoted strings.
    """
    content = Path(filepath).read_text(encoding="utf-8")
    return _parse_content(content)


def _parse_content(
    content: str,
    skip_commands_for: set[str] | None = None,
    on_bind: Callable[[str, str], None] | None = None,
) -> dict[str, str]:
    """Parse .env file content and return key-value pairs."""
    result: dict[str, str] = {}
    pos = 0
    length = len(content)

    while pos < length:
        # Skip whitespace and empty lines
        while pos < length and content[pos] in " \t\r\n":
            pos += 1

        if pos >= length:
            break

        # Skip comment lines
        if content[pos] == "#":
            pos = _skip_to_eol(content, pos)
            continue

        # Try to parse a binding
        parsed = _parse_binding(content, pos, result, skip_commands_for)
        if parsed:
            key, value, new_pos = parsed
            result[key] = value
            if on_bind:
                on_bind(key, value)
            pos = new_pos
        else:
            # Skip to next line on parse failure
            pos = _skip_to_eol(content, pos)

    return result


def _skip_to_eol(content: str, pos: int) -> int:
    """Skip to end of line, return position after newline."""
    while pos < len(content) and content[pos] not in "\r\n":
        pos += 1
    if pos < len(content) and content[pos] == "\r":
        pos += 1
    if pos < len(content) and content[pos] == "\n":
        pos += 1
    return pos


def _parse_binding(
    content: str,
    pos: int,
    context: dict[str, str],
    skip_commands_for: set[str] | None = None,
) -> tuple[str, str, int] | None:
    """Parse a KEY=value binding, return (key, value, new_pos) or None."""
    length = len(content)

    # Skip optional 'export ' prefix
    if content[pos : pos + 7] == "export ":
        pos += 7
        while pos < length and content[pos] in " \t":
            pos += 1

    # Parse key
    key_start = pos
    while pos < length and (content[pos].isalnum() or content[pos] == "_"):
        pos += 1

    if pos == key_start:
        return None

    key = content[key_start:pos]

    # Must start with letter or underscore
    if not (key[0].isalpha() or key[0] == "_"):
        return None

    # Skip whitespace before =
    while pos < length and content[pos] in " \t":
        pos += 1

    # Expect =
    if pos >= length or content[pos] != "=":
        return None
    pos += 1

    # Skip whitespace after =
    while pos < length and content[pos] in " \t":
        pos += 1

    # If key already exists in env and we should skip commands, use existing value
    if skip_commands_for and key in skip_commands_for:
        # Skip to end of line without executing commands
        new_pos = _skip_to_eol(content, pos)
        return key, os.environ[key], new_pos

    # Parse value (with command expansion)
    value, pos = _parse_value(content, pos, context)

    return key, value, pos


def _parse_value(content: str, pos: int, context: dict[str, str]) -> tuple[str, int]:
    """Parse a value starting at pos, return (value, new_pos)."""
    if pos >= len(content) or content[pos] in "\r\n":
        return "", pos

    char = content[pos]

    # Single-quoted: literal value (no escape, no expansion), supports multiline
    if char == "'":
        return _parse_single_quoted(content, pos)

    # Double-quoted: process escapes, variable expansion, and commands, supports multiline
    if char == '"':
        value, pos = _parse_double_quoted(content, pos)
        value = _expand_variables(value, context)
        value = _expand_commands(value)
        value = value.replace(_ESCAPED_DOLLAR, "$")  # Restore escaped $
        return value, pos

    # Unquoted value: variable expansion and command substitution
    return _parse_unquoted(content, pos, context)


def _parse_single_quoted(content: str, pos: int) -> tuple[str, int]:
    """Parse single-quoted value (literal, multiline supported)."""
    pos += 1  # Skip opening quote
    start = pos
    length = len(content)

    while pos < length:
        if content[pos] == "'":
            value = content[start:pos]
            return value, pos + 1
        pos += 1

    # No closing quote found, return what we have
    return content[start:], pos


def _parse_double_quoted(content: str, pos: int) -> tuple[str, int]:
    """Parse double-quoted value (with escapes, multiline supported)."""
    pos += 1  # Skip opening quote
    result = []
    length = len(content)

    while pos < length:
        char = content[pos]

        if char == "\\" and pos + 1 < length:
            next_char = content[pos + 1]
            if next_char == "n":
                result.append("\n")
            elif next_char == "t":
                result.append("\t")
            elif next_char == "r":
                result.append("\r")
            elif next_char == '"':
                result.append('"')
            elif next_char == "\\":
                result.append("\\")
            elif next_char == "$":
                result.append(_ESCAPED_DOLLAR)  # Placeholder to prevent expansion
            else:
                # Unknown escape, keep both characters
                result.append(char)
                result.append(next_char)
            pos += 2
        elif char == '"':
            return "".join(result), pos + 1
        else:
            result.append(char)
            pos += 1

    # No closing quote found, return what we have
    return "".join(result), pos


def _parse_unquoted(content: str, pos: int, context: dict[str, str]) -> tuple[str, int]:
    """Parse unquoted value (until comment or end of line)."""
    result = []
    length = len(content)

    while pos < length and content[pos] not in "\r\n":
        char = content[pos]

        # Stop at inline comment (whitespace followed by #)
        if char == "#" and result and result[-1] in " \t":
            # Remove trailing whitespace
            while result and result[-1] in " \t":
                result.pop()
            break

        # Handle backslash escapes (like bash)
        if char == "\\" and pos + 1 < length:
            next_char = content[pos + 1]
            if next_char == "$":
                result.append(_ESCAPED_DOLLAR)  # Placeholder to prevent expansion
                pos += 2
                continue
            elif next_char == "\\":
                result.append("\\")
                pos += 2
                continue
            # Other backslashes kept as-is

        result.append(char)
        pos += 1

    value = "".join(result).rstrip()

    # Expand variables, then commands
    value = _expand_variables(value, context)
    value = _expand_commands(value)
    value = value.replace(_ESCAPED_DOLLAR, "$")  # Restore escaped $
    return value, pos


def _expand_variables(value: str, context: dict[str, str]) -> str:
    """Expand $VAR and ${VAR} references in value.

    Looks up variables in context (previously parsed .env vars) first,
    then falls back to os.environ. Unknown variables expand to empty string.
    """

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        # Check context first (vars defined earlier in .env), then os.environ
        if var_name in context:
            return context[var_name]
        return os.environ.get(var_name, "")

    # Expand ${VAR} first (more specific), then $VAR
    value = _VAR_BRACE_RE.sub(replacer, value)
    value = _VAR_BARE_RE.sub(replacer, value)
    return value


def _expand_commands(value: str) -> str:
    """Expand all $(command) substitutions in value.

    Handles nested parentheses within commands, e.g., $(echo "(test)").
    """
    result = []
    i = 0
    length = len(value)

    while i < length:
        # Look for $(
        if i + 1 < length and value[i] == "$" and value[i + 1] == "(":
            # Find matching closing paren, accounting for nesting
            cmd_start = i + 2
            depth = 1
            j = cmd_start

            while j < length and depth > 0:
                if value[j] == "(":
                    depth += 1
                elif value[j] == ")":
                    depth -= 1
                j += 1

            if depth == 0:
                # Found matching ), extract and execute command
                command = value[cmd_start : j - 1]
                output = _execute_command(command)
                result.append(output)
                i = j
            else:
                # No matching ), keep literal
                result.append(value[i])
                i += 1
        else:
            result.append(value[i])
            i += 1

    return "".join(result)


def _execute_command(command: str, timeout: float = 5.0) -> str:
    """Execute a shell command and return stdout."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""
