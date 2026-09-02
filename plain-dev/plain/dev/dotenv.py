"""Bash-compatible `.env` file parsing and Plain dev/test dotenv loading.

`plain.dev` owns all dotenv code so that production deployments (which don't
install plain.dev) never load `.env` files. plain.pytest opportunistically
imports `load_dotenv_files` — if plain.dev is installed, `.env.test*` loads
under pytest; if not, the plugin skips dotenv loading entirely.

Parser supports:
- KEY=value (basic unquoted)
- KEY="double quoted value" (with escape handling and multiline)
- KEY='single quoted value' (literal, including multiline)
- export KEY=value (strips export prefix)
- Comments (# comment and inline KEY=value # comment)
- Variable expansion: $VAR and ${VAR} (in unquoted and double-quoted values)
- Command substitution: $(command)
- Encrypted values: KEY=encrypted:<token>, decrypted with DEV_ENV_KEY

`encrypted:` is recognized syntactically — at the start of an *unquoted* value,
before anything is expanded. So an encrypted value is never expanded, and
quoting it (`KEY='encrypted:aes'`) makes it ordinary text.

Encrypted values are resolved in a second phase, after parsing. `load_dotenv_files`
resolves once after every file has loaded, so the key line can live in
`.env.dev.local`, in the shell, or as a committed `DEV_ENV_KEY=$(op read ...)`
reference next to the values themselves. Decrypted plaintext is bound literally —
no variable expansion or command substitution.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import click
from plain.exceptions import ImproperlyConfigured

__all__ = ["load_dotenv", "load_dotenv_files", "parse_dotenv"]

# Environment variable holding the project's Fernet key.
ENV_KEY_VAR = "DEV_ENV_KEY"
# Written form of an encrypted value: `KEY=encrypted:<fernet token>`.
ENCRYPTED_VALUE_PREFIX = "encrypted:"

# Match ${VAR} or $VAR (VAR must start with letter/underscore, then alphanumeric/underscore)
_VAR_BRACE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_VAR_BARE_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
# Placeholder for escaped $ (to prevent expansion)
_ESCAPED_DOLLAR = "\x00DOLLAR\x00"

_PLAIN_ENV_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
_files_loaded = False

# Which file bound each key, filled in as files load. A key already in the
# environment before any file loaded (exported in the shell) is simply absent.
# `plain env set` reads this to warn about a name it can't actually change.
bound_sources: dict[str, Path] = {}


class Binding(NamedTuple):
    """One `KEY=value` binding, and where it sits in the content it came from.

    `key_start` is the first character of the key, so any `export ` prefix and
    indentation are kept, and `value_end` is just past the value, so an inline
    comment, the line ending, or a further binding on the same line is kept too.
    `value` is the value as the parser read it — quotes removed and escapes
    processed, and expanded only if the parser was expanding.
    """

    key: str
    value: str
    encrypted: bool
    source: Path | None
    key_start: int
    value_end: int


# --- the ladder and the loaders ---


def dotenv_ladder(plain_env: str) -> list[str]:
    """The `.env` files that load, highest precedence first.

    1. `.env.{plain_env}.local`  — gitignored, env-specific personal
    2. `.env.local`              — gitignored, personal; SKIPPED in test
    3. `.env.{plain_env}`        — gitignored or committed, env-specific
    4. `.env`                    — committed baseline
    """
    paths = []
    if plain_env:
        paths.append(f".env.{plain_env}.local")
    if plain_env != "test":
        # Skipped under test (Next.js / Rails dotenv convention) so CI runs
        # stay deterministic and personal creds don't leak into the suite.
        paths.append(".env.local")
    if plain_env:
        paths.append(f".env.{plain_env}")
    paths.append(".env")
    return paths


def load_dotenv_files(*, decrypt: bool = True) -> None:
    """Load `.env` files using Next.js / Vite-style precedence.

    Files load in `dotenv_ladder()` order — `load_dotenv()` doesn't override
    existing keys, so the first file to bind a key wins.

    `PLAIN_ENV` is set by the CLI dispatcher (`plain.cli.core`) based on the
    active command — `plain dev` → `dev`, `plain test` → `test` — and by
    `plain env`, which sets its own. Export `PLAIN_ENV` yourself to override.

    With `decrypt=False`, plain values bind as usual and encrypted ones are
    left unbound: no key is needed, and nothing fails. That's what `plain env`
    loads with, since it's the command you run when decryption can't work yet.

    Idempotent within a process — repeat calls are a no-op.
    """
    global _files_loaded
    if _files_loaded:
        return
    _files_loaded = True

    plain_env = os.environ.get("PLAIN_ENV", "")
    if plain_env and not _PLAIN_ENV_RE.fullmatch(plain_env):
        raise ValueError(
            f"PLAIN_ENV must match {_PLAIN_ENV_RE.pattern}, got {plain_env!r}"
        )

    bound_sources.clear()

    # Encrypted values from every file are collected here and decrypted once
    # at the end, so DEV_ENV_KEY can come from any file (or the shell).
    deferred: dict[str, Binding] = {}

    for path in dotenv_ladder(plain_env):
        if _load_dotenv_deferring_encrypted(path, override=False, deferred=deferred):
            click.secho(f"Loading {path}...", dim=True, italic=True, err=True)

    if decrypt:
        _bind_decrypted(deferred)


def load_dotenv(
    filepath: str | Path,
    *,
    override: bool = False,
    decrypt: bool = True,
) -> bool:
    """
    Load environment variables from a .env file into os.environ.

    Args:
        filepath: Path to the .env file
        override: If True, overwrite existing environment variables
        decrypt: If False, leave encrypted values unbound instead of decrypting

    Returns:
        True if the file was loaded, False if it doesn't exist

    Encrypted values are decrypted with DEV_ENV_KEY once the whole file has
    been parsed, so the key may be defined earlier in the same file.
    """
    deferred: dict[str, Binding] = {}
    loaded = _load_dotenv_deferring_encrypted(
        filepath, override=override, deferred=deferred
    )
    if not loaded:
        return False
    if decrypt:
        _bind_decrypted(deferred)
    return True


def parse_dotenv(filepath: str | Path, *, decrypt: bool = True) -> dict[str, str]:
    """
    Parse a .env file and return a dictionary of key-value pairs.

    Does not modify os.environ. Supports multiline values in quoted strings.
    Encrypted values are decrypted with DEV_ENV_KEY from os.environ, falling
    back to a `DEV_ENV_KEY=` line in the file itself.
    """
    path = Path(filepath)
    content = path.read_text(encoding="utf-8")

    encrypted: list[Binding] = []

    def collect(binding: Binding) -> None:
        if binding.encrypted:
            encrypted.append(binding)

    result = _FileParser(content, source=path).parse(collect)
    if not decrypt:
        return result

    env_key = os.environ.get(ENV_KEY_VAR) or result.get(ENV_KEY_VAR)
    for binding in encrypted:
        result[binding.key] = decrypt_env_binding(binding, env_key=env_key)
    return result


def _load_dotenv_deferring_encrypted(
    filepath: str | Path,
    *,
    override: bool,
    deferred: dict[str, Binding],
) -> bool:
    """Bind a file's plain values now and collect its encrypted ones in `deferred`.

    A key with a deferred value counts as bound: a later file (or a later line)
    can't take it over, which keeps first-file-wins precedence intact.
    """
    path = Path(filepath)
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")

    # Keys that are already bound: their values are located but not expanded,
    # so nothing in them runs and nothing in them is decrypted.
    skip_for = None if override else set(os.environ) | deferred.keys()

    def on_bind(binding: Binding) -> None:
        key = binding.key
        if not override and (key in os.environ or key in deferred):
            return
        if override:
            deferred.pop(key, None)
        if binding.encrypted:
            deferred[key] = binding
        else:
            os.environ[key] = binding.value
        bound_sources[key] = path

    _FileParser(
        content,
        source=path,
        skip_for=skip_for,
        encrypted_names=set(deferred),
    ).parse(on_bind)
    return True


def _bind_decrypted(deferred: dict[str, Binding]) -> None:
    """Decrypt every deferred binding with DEV_ENV_KEY and bind the plaintext literally."""
    for binding in deferred.values():
        os.environ[binding.key] = decrypt_env_binding(binding)


# --- encrypted values ---


def decrypt_env_binding(binding: Binding, env_key: str | None = None) -> str:
    """Decrypt one binding, or raise ImproperlyConfigured saying exactly what is wrong."""
    from cryptography.fernet import InvalidToken

    if env_key is None:
        env_key = os.environ.get(ENV_KEY_VAR, "")

    if not env_key:
        if ENV_KEY_VAR in os.environ:
            raise ImproperlyConfigured(
                f"{binding.key} in {binding.source} is encrypted, but {ENV_KEY_VAR} is "
                f"set to an empty value. If it is bound with a command like "
                f'{ENV_KEY_VAR}=$(op read "op://..."), that command failed — run it '
                "yourself to see why."
            )
        plain_env = os.environ.get("PLAIN_ENV", "")
        key_file_hint = f".env.{plain_env}.local" if plain_env else ".env.local"
        raise ImproperlyConfigured(
            f"{binding.key} in {binding.source} is encrypted, but {ENV_KEY_VAR} is not set. "
            f"Set {ENV_KEY_VAR} to this project's key — usually with a line in {key_file_hint} "
            f'like {ENV_KEY_VAR}=$(op read "op://..."), or commit that reference line in '
            f"{binding.source} so teammates get it too. Generate a new key with `plain env key`."
        )

    try:
        return decrypt_env_value(binding.value, env_key)
    except (InvalidToken, ValueError) as e:
        raise ImproperlyConfigured(
            f"{ENV_KEY_VAR} does not decrypt {binding.key} in {binding.source}. "
            "Check that it is this project's key. If the value is meant to be the "
            f"literal text and not an encrypted value, quote it: "
            f"{binding.key}='{ENCRYPTED_VALUE_PREFIX}...'"
        ) from e


def is_encrypted_value(value: str) -> bool:
    """True when a value is written in the `encrypted:<token>` form.

    A syntactic test on the text as written — an unquoted value starting with
    `encrypted:` is an encrypted value, and a token that doesn't decrypt is an
    error rather than plain text.
    """
    return value.startswith(ENCRYPTED_VALUE_PREFIX)


def generate_env_key() -> str:
    """Generate a new DEV_ENV_KEY (a Fernet key: urlsafe base64, 44 chars)."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def encrypt_env_value(plaintext: str, env_key: str) -> str:
    """Encrypt a plaintext string into the `encrypted:<token>` form."""
    from cryptography.fernet import Fernet

    token = Fernet(env_key.encode("ascii")).encrypt(plaintext.encode("utf-8"))
    return ENCRYPTED_VALUE_PREFIX + token.decode("ascii")


def decrypt_env_value(value: str, env_key: str) -> str:
    """Decrypt an `encrypted:<token>` value back to its plaintext string.

    Raises `cryptography.fernet.InvalidToken` when the key doesn't match or the
    token is malformed, and `ValueError` when `value` isn't in the encrypted
    form or the key itself is malformed.
    """
    from cryptography.fernet import Fernet

    if not is_encrypted_value(value):
        raise ValueError(f"Not an {ENCRYPTED_VALUE_PREFIX} value")
    token = value.removeprefix(ENCRYPTED_VALUE_PREFIX).encode("ascii")
    return Fernet(env_key.encode("ascii")).decrypt(token).decode("utf-8")


# --- finding a binding to rewrite ---


def find_env_binding(
    content: str, name: str, *, source: Path | None = None
) -> Binding | None:
    """Find the first `NAME=...` binding in .env file content, without evaluating anything.

    This runs the loader's own parser in raw mode, so what counts as a binding
    here — `export NAME=`, whitespace around `=`, quoted values spanning lines,
    a second binding on the same line — is exactly what counts when the file is
    loaded. `source` is only recorded on the binding, for error messages.
    """
    found: Binding | None = None

    def match(binding: Binding) -> None:
        nonlocal found
        if found is None and binding.key == name:
            found = binding

    _FileParser(content, source=source, expand=False).parse(match)
    return found


# --- the parser ---


class _FileParser:
    """Parses the content of one .env file, top to bottom.

    Everything a value can see or must refuse belongs to the file it is written
    in — the values bound earlier in the same file, the names bound to an
    encrypted value, the file's own path for error messages — so it lives on the
    parser instead of being threaded through every step of parsing a value.
    """

    def __init__(
        self,
        content: str,
        *,
        source: Path | None = None,
        skip_for: set[str] | None = None,
        encrypted_names: set[str] | None = None,
        expand: bool = True,
    ) -> None:
        """
        Args:
            content: The file's text
            source: The file it was read from, for error messages
            skip_for: Keys that are already bound, whose values are located but
                never evaluated
            encrypted_names: Names already bound to an encrypted value, which
                can't be referenced from another value; encrypted keys met in
                this file are added as we go
            expand: If False, parse without expanding or running anything
        """
        self.content = content
        self.source = source
        self.skip_for = skip_for or set()
        self.expand = expand
        # Values bound earlier in this file, which later values can reference.
        self.result: dict[str, str] = {}
        self.encrypted_names = set(encrypted_names) if encrypted_names else set()

    def parse(self, on_bind: Callable[[Binding], None]) -> dict[str, str]:
        """Parse the whole file, calling `on_bind` with each binding, and return the key-value pairs."""
        pos = 0
        length = len(self.content)

        while pos < length:
            # Skip whitespace and empty lines
            while pos < length and self.content[pos] in " \t\r\n":
                pos += 1

            if pos >= length:
                break

            # Skip comment lines
            if self.content[pos] == "#":
                pos = _skip_to_eol(self.content, pos)
                continue

            binding = self._binding(pos)
            if binding is None:
                # Skip to next line on parse failure
                pos = _skip_to_eol(self.content, pos)
                continue

            self.result[binding.key] = binding.value
            if binding.encrypted:
                self.encrypted_names.add(binding.key)
            on_bind(binding)
            pos = binding.value_end

        return self.result

    def _binding(self, pos: int) -> Binding | None:
        """Parse a KEY=value binding starting at `pos`, or return None if there isn't one."""
        content = self.content
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

        # If the key is already bound, parse the value only to find where it ends
        # (it may span lines when quoted) and keep the value already in place.
        if key in self.skip_for:
            _, value_end = self._value(pos, key, expand=False)
            return Binding(
                key=key,
                value=os.environ.get(key, ""),
                encrypted=False,
                source=self.source,
                key_start=key_start,
                value_end=value_end,
            )

        # `encrypted:` at the start of an unquoted value is the encrypted form. It's
        # recognized here, on the text as written, so the token is never expanded —
        # and so a quoted value (which can't start with `e`) is always plain text.
        if content.startswith(ENCRYPTED_VALUE_PREFIX, pos):
            value, value_end = self._value(pos, key, expand=False)
            return Binding(
                key=key,
                value=value,
                encrypted=True,
                source=self.source,
                key_start=key_start,
                value_end=value_end,
            )

        value, value_end = self._value(pos, key, expand=self.expand)
        return Binding(
            key=key,
            value=value,
            encrypted=False,
            source=self.source,
            key_start=key_start,
            value_end=value_end,
        )

    def _value(self, pos: int, key: str, *, expand: bool) -> tuple[str, int]:
        """Parse `key`'s value starting at pos, return (value, position just past it)."""
        content = self.content

        if pos >= len(content) or content[pos] in "\r\n":
            return "", pos

        char = content[pos]

        # Single-quoted: literal value (no escape, no expansion), supports multiline
        if char == "'":
            return _parse_single_quoted(content, pos)

        # Double-quoted: process escapes, variable expansion, and commands, supports multiline
        if char == '"':
            value, pos = _parse_double_quoted(content, pos)
            if expand:
                value = self._expand_variables(value, key)
                value = _expand_commands(value)
            value = value.replace(_ESCAPED_DOLLAR, "$")  # Restore escaped $
            return value, pos

        # Unquoted value: variable expansion and command substitution
        return self._unquoted(pos, key, expand=expand)

    def _unquoted(self, pos: int, key: str, *, expand: bool) -> tuple[str, int]:
        """Parse an unquoted value (until an inline comment or the end of the line)."""
        content = self.content
        start = pos
        result = []
        length = len(content)

        while pos < length and content[pos] not in "\r\n":
            char = content[pos]

            # Stop at inline comment (whitespace followed by #)
            if char == "#" and result and result[-1] in " \t":
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

        # The value ends at its last non-whitespace character, so an inline comment
        # or the line ending stays where it is.
        while pos > start and content[pos - 1] in " \t":
            pos -= 1

        value = "".join(result).rstrip()

        # Expand variables, then commands
        if expand:
            value = self._expand_variables(value, key)
            value = _expand_commands(value)
        value = value.replace(_ESCAPED_DOLLAR, "$")  # Restore escaped $
        return value, pos

    def _expand_variables(self, value: str, key: str) -> str:
        """Expand $VAR and ${VAR} references in `key`'s value.

        Looks up variables in the values parsed so far first, then falls back to
        os.environ. Unknown variables expand to an empty string. Referencing an
        encrypted value is an error — it hasn't been decrypted yet, so expanding it
        would either paste in the ciphertext or bind nothing at all.
        """

        def replacer(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name in self.encrypted_names:
                raise ImproperlyConfigured(
                    f"{key} in {self.source} references {var_name}, which "
                    "is an encrypted value. Encrypted values can't be referenced "
                    "from other values."
                )
            # Check values defined earlier in this file, then os.environ
            if var_name in self.result:
                return self.result[var_name]
            return os.environ.get(var_name, "")

        # Expand ${VAR} first (more specific), then $VAR
        value = _VAR_BRACE_RE.sub(replacer, value)
        value = _VAR_BARE_RE.sub(replacer, value)
        return value


def _skip_to_eol(content: str, pos: int) -> int:
    """Skip to end of line, return position after newline."""
    while pos < len(content) and content[pos] not in "\r\n":
        pos += 1
    if pos < len(content) and content[pos] == "\r":
        pos += 1
    if pos < len(content) and content[pos] == "\n":
        pos += 1
    return pos


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
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""
