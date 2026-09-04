"""`plain env` — encrypted values in committed `.env` files.

A value written as `KEY=encrypted:<token>` is decrypted by the dotenv loader
with `DEV_ENV_KEY`. These commands generate that key, and read and write
encrypted values. The loader itself lives in `plain.dev.dotenv`.

`cli` reaches the top-level `plain` CLI through the `plain.cli` entry point
group, so it runs without `plain.runtime.setup()` — it's the command you reach
for exactly when loading the app would fail: a fresh clone with no key, or a
rotation to a new one. It loads the `.env` ladder itself, without decrypting.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import click
from plain.exceptions import ImproperlyConfigured

from .dotenv import (
    ENV_KEY_VAR,
    bound_sources,
    decrypt_env_binding,
    dotenv_ladder,
    encrypt_env_value,
    find_env_binding,
    generate_env_key,
    load_dotenv_files,
)

_ENV_KEY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Both commands take the same --file option.
_env_file_option = click.option(
    "--file",
    "-f",
    "file_path",
    default=None,
    help="The .env file to use. Defaults to .env.{PLAIN_ENV}, normally .env.dev.",
)


def prepare_env() -> None:
    """Load the `.env` ladder for these commands, without decrypting anything.

    `plain env` edits `.env.dev` by default, so it loads the dev ladder to find
    DEV_ENV_KEY. Nothing is decrypted on the way in: existing values may be
    under a key you don't have yet, or under the old key you're rotating away
    from, and neither should stop you from running these commands.
    """
    os.environ.setdefault("PLAIN_ENV", "dev")
    try:
        load_dotenv_files(decrypt=False)
    except ImproperlyConfigured as e:
        # These commands run without app setup, so nothing above us renders an
        # ImproperlyConfigured — and a traceback is the wrong answer for a
        # problem in a `.env` file.
        raise click.ClickException(str(e)) from e


@click.group()
def cli() -> None:
    """Encrypted values in committed .env files."""
    prepare_env()


@cli.command()
def key() -> None:
    """Generate a new DEV_ENV_KEY (printed alone on stdout, so it can be piped)."""
    click.echo(generate_env_key())
    click.secho(
        f"Store this key somewhere durable (1Password, your keychain) and bind it as {ENV_KEY_VAR}.\n"
        f'For example, in .env.dev.local: {ENV_KEY_VAR}=$(op read "op://Vault/item/field")',
        dim=True,
        err=True,
    )


@cli.command("set")
@click.argument("name")
@click.argument("value", required=False)
@_env_file_option
def set_value(name: str, value: str | None, file_path: str | None) -> None:
    """Encrypt VALUE and write NAME=encrypted:... into the file.

    With no VALUE, the value is read from stdin (so multi-line secrets work:
    `plain env set GITHUB_APP_PRIVATE_KEY < key.pem`).

    Values already in the file are never read, so `DEV_ENV_KEY=<new key>
    plain env set ...` re-encrypts one value under a new key.
    """
    from cryptography.fernet import Fernet

    _validate_name(name)
    env_key = _require_env_key()

    # Check the key by itself, so a problem with the value can't be reported
    # as a bad key.
    try:
        Fernet(env_key.encode("ascii"))
    except ValueError as e:
        raise click.ClickException(
            f"{ENV_KEY_VAR} is not a valid key (expected a 44 character key from `plain env key`)"
        ) from e

    if value is None:
        if _stdin_is_a_tty():
            raise click.ClickException(
                "Pass VALUE as an argument, or pipe it in: plain env set NAME < file"
            )
        try:
            value = sys.stdin.read().removesuffix("\n")
        except UnicodeDecodeError as e:
            raise click.ClickException("VALUE is not valid UTF-8 text") from e

    binding_line = f"{name}={encrypt_env_value(value, env_key)}"

    # newline="" keeps the file's line endings exactly as they are
    path = _env_file_path(file_path)
    content = path.read_text(encoding="utf-8", newline="") if path.exists() else ""

    binding = find_env_binding(content, name, source=path)
    if binding:
        content = (
            content[: binding.key_start] + binding_line + content[binding.value_end :]
        )
    else:
        line_ending = "\r\n" if "\r\n" in content else "\n"
        if content and not content.endswith("\n"):
            content += line_ending
        content += binding_line + line_ending

    path.write_text(content, encoding="utf-8", newline="")
    click.echo(f"Wrote {binding_line} to {path}")

    if _is_gitignored(path):
        click.secho(
            f"Warning: {path} is gitignored, so this value will not be committed. "
            "Encrypted values are meant to be committed — if .gitignore has a `.env*` "
            "rule, replace it with `.env.local` and `.env.*.local`.",
            fg="yellow",
            err=True,
        )

    _warn_if_shadowed(name, path)


@cli.command()
@click.argument("name")
@_env_file_option
def get(name: str, file_path: str | None) -> None:
    """Decrypt NAME from the file and print the plaintext to stdout."""
    path = _env_file_path(file_path)
    if not path.exists():
        raise click.ClickException(f"{path} does not exist")

    binding = find_env_binding(path.read_text(encoding="utf-8"), name, source=path)
    if binding is None:
        raise click.ClickException(f"{name} is not set in {path}")

    if not binding.encrypted:
        click.secho(
            f"{name} in {path} is not encrypted (printing it as written)",
            fg="yellow",
            err=True,
        )
        click.echo(binding.value)
        return

    try:
        plaintext = decrypt_env_binding(binding)
    except ImproperlyConfigured as e:
        raise click.ClickException(str(e)) from e

    click.echo(plaintext)


def _env_file_path(file_path: str | None) -> Path:
    return Path(file_path or f".env.{os.environ.get('PLAIN_ENV', 'dev')}")


def _validate_name(name: str) -> None:
    if not _ENV_KEY_NAME_RE.fullmatch(name):
        raise click.ClickException(
            f"{name!r} is not a valid environment variable name "
            "(letters, digits and underscores, not starting with a digit)"
        )


def _require_env_key() -> str:
    """The DEV_ENV_KEY already loaded into the environment, or a clear error."""
    env_key = os.environ.get(ENV_KEY_VAR, "")
    if env_key:
        return env_key

    if ENV_KEY_VAR in os.environ:
        raise click.ClickException(
            f"{ENV_KEY_VAR} is set to an empty value. If it is bound with a command "
            f'like {ENV_KEY_VAR}=$(op read "op://..."), that command failed — run it '
            "yourself to see why."
        )

    raise click.ClickException(
        f"{ENV_KEY_VAR} is not set. Generate one with `plain env key`, then bind it "
        "in your environment (see the plain.dev README)."
    )


def _warn_if_shadowed(name: str, target: Path) -> None:
    """Warn when something that loads before `target` already binds `name`.

    The value would be written and committed, and then quietly ignored on this
    machine, because the first file to bind a key wins.
    """
    if name not in os.environ:
        return

    source = bound_sources.get(name)
    if source is None:
        # Not bound by any file, so it came from the shell — which always wins.
        where = "your shell environment"
    elif _ladder_rank(source) < _ladder_rank(target):
        where = str(source)
    else:
        return

    click.secho(
        f"Warning: {name} is also set in {where}, which outranks {target}; "
        "the encrypted value will not be used on this machine.",
        fg="yellow",
        err=True,
    )


def _ladder_rank(path: Path) -> int:
    """Where a file sits in the load order — the lower the rank, the earlier it wins."""
    ladder = dotenv_ladder(os.environ.get("PLAIN_ENV", ""))
    if str(path) in ladder:
        return ladder.index(str(path))
    return len(ladder)  # a file that isn't loaded at all, so everything outranks it


def _stdin_is_a_tty() -> bool:
    return sys.stdin.isatty()


def _is_gitignored(path: Path) -> bool:
    # Drop GIT_* from the environment for the same reason `_run_git` in
    # plain/dev/postgres/identity.py does: a `plain` command run from a git
    # hook would otherwise resolve against the hook's repository.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            capture_output=True,
            check=False,
            env=env,
        )
    except OSError:
        return False
    return result.returncode == 0
