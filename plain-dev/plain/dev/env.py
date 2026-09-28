"""`plain env` — encrypted values in committed `.env` files.

A value written as `KEY=encrypted:<token>` is decrypted by the dotenv loader
with the project's key. The key lives on each machine in `~/.plain/env-keys/`,
named by its id, and the file names it with a plain `PLAIN_ENV_KEY_ID=<id>` line
— so nothing in a working tree is ever a secret. These commands manage the key
(`init`, `unlock`, `lock`, `rotate`) and read and write encrypted values
(`set`, `get`). The loader lives in `plain.dev.dotenv`, the key store in
`plain.dev.envkeys`.

`cli` reaches the top-level `plain` CLI through the `plain.cli` entry point
group, so it runs without `plain.runtime.setup()` — it's the command you reach
for exactly when loading the app would fail: a fresh clone with no key, or a
rotation to a new one. It loads the `.env` ladder itself, without decrypting.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
from plain.exceptions import ImproperlyConfigured

from .dotenv import (
    Binding,
    bound_sources,
    decrypt_env_binding,
    dotenv_ladder,
    encrypt_env_value,
    env_key_from_environment,
    find_env_binding,
    find_env_bindings,
    key_line_of,
    load_dotenv_files,
    loaded_directives,
    named_key_id,
)
from .envkeys import (
    ENV_KEY_ID_VAR,
    ENV_KEY_VAR,
    INVALID_ENV_KEY_HINT,
    KEY_LINE_NAMES,
    env_key_id,
    generate_env_key,
    is_valid_env_key,
    resolve_env_key,
    store_env_key,
    stored_env_key_path,
)

_ENV_KEY_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Every command takes the same --file option.
_env_file_option = click.option(
    "--file",
    "-f",
    "file_path",
    default=None,
    help="The .env file to use. Defaults to .env.{PLAIN_ENV}, normally .env.dev.",
)


class _EnvGroup(click.Group):
    """Renders a `.env` problem as a CLI error instead of a traceback.

    These commands run without app setup, so nothing above us turns an
    `ImproperlyConfigured` into something readable. Doing it here covers the
    group callback and every subcommand, so a new command can't forget to.
    """

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except ImproperlyConfigured as e:
            raise click.ClickException(str(e)) from e


def prepare_env() -> None:
    """Load the `.env` ladder for these commands, without decrypting anything.

    `plain env` edits `.env.dev` by default, so it loads the dev ladder to find
    the key id. Nothing is decrypted on the way in: existing values may be
    under a key you don't have yet, or under the old key you're rotating away
    from, and neither should stop you from running these commands.
    """
    os.environ.setdefault("PLAIN_ENV", "dev")
    load_dotenv_files(decrypt=False)


@click.group(cls=_EnvGroup)
def cli() -> None:
    """Encrypted values in committed .env files."""
    prepare_env()


@cli.command()
@_env_file_option
def init(file_path: str | None) -> None:
    """Generate the project's key, store it on this machine, and name it in the file."""
    path = _env_file_path(file_path)
    content = _read(path)
    bindings = find_env_bindings(content)

    # The key is one per ladder, so a file elsewhere in it that names one is
    # as much a reason to stop as this file naming one.
    named_here = _key_id_named_by(bindings)
    if named := named_here or named_key_id(loaded_directives()):
        where = path if named_here else bound_sources[ENV_KEY_ID_VAR]
        raise click.ClickException(
            f"{where} already names key {named}. `plain env unlock` adds that key to "
            "this machine; `plain env rotate` replaces it with a new one."
        )
    if _encrypted(bindings):
        # A new key can't open these, and naming it here would make the file
        # claim otherwise. The key that does open them belongs in `unlock`.
        raise click.ClickException(
            f"{path} already has encrypted values. Pipe the key they were encrypted "
            "with into `plain env unlock` instead of generating a new one."
        )

    env_key = generate_env_key()
    key_id = env_key_id(env_key)
    stored = store_env_key(env_key)
    _write(path, _with_binding(content, ENV_KEY_ID_VAR, key_id))
    click.echo(f"Wrote {ENV_KEY_ID_VAR}={key_id} to {path}")
    click.secho(
        f"The key is in {stored}. Keep a copy somewhere durable that your team can "
        "reach (a shared vault); another machine adds it with `plain env unlock`.",
        dim=True,
        err=True,
    )


@cli.command()
@_env_file_option
def unlock(file_path: str | None) -> None:
    """Store the project's key on this machine, read from stdin.

    `op read "op://Vault/item/field" | plain env unlock` — the key never goes
    through a terminal or a shell history. A file that doesn't name its key
    yet gets its PLAIN_ENV_KEY_ID line, once the key is checked against the
    values already in it; a leftover key line from the first version is what
    the id line replaces.
    """
    if _stdin_is_a_tty():
        raise click.ClickException(
            'Pipe the key in: op read "op://Vault/item/field" | plain env unlock'
        )
    try:
        env_key = sys.stdin.read().strip()
    except UnicodeDecodeError as e:
        raise click.ClickException(f"That {INVALID_ENV_KEY_HINT}") from e
    if not is_valid_env_key(env_key):
        raise click.ClickException(f"That {INVALID_ENV_KEY_HINT}")
    key_id = env_key_id(env_key)

    path = _env_file_path(file_path)
    content = _read(path)
    bindings = find_env_bindings(content)
    named = _key_id_named_by(bindings)
    if named and named != key_id:
        raise click.ClickException(
            f"That is key {key_id}, but {path} names key {named}. Get the key {path} "
            "was encrypted with, or, if this key is meant to replace it, `plain env "
            "rotate` is how a file changes keys."
        )

    if not named:
        # The file is being brought over from a key that lived elsewhere: make
        # sure this is that key before writing its id in.
        for binding in _encrypted(bindings):
            _decrypt_or_fail(
                binding,
                env_key=env_key,
                problem=f"Key {key_id} does not decrypt {binding.key} in {path}, so "
                "it is not the key this file was encrypted with.",
            )

    stored = store_env_key(env_key)
    click.echo(f"Stored key {key_id} in {stored}")

    key_lines = [b for b in bindings if b.key in KEY_LINE_NAMES]
    if not named:
        if key_lines:
            old_line = key_lines.pop(0)
            content = _replace_binding(content, old_line, ENV_KEY_ID_VAR, key_id)
            click.echo(
                f"Replaced the {old_line.key}= line in {path} with {ENV_KEY_ID_VAR}={key_id}"
            )
        else:
            content = _with_binding(content, ENV_KEY_ID_VAR, key_id)
            click.echo(f"Wrote {ENV_KEY_ID_VAR}={key_id} to {path}")
        _write(path, content)

    for line in key_lines:
        click.secho(
            f"Warning: {path} still has a {line.key}= line. The key now comes from "
            "this machine's store, and $(...) no longer runs in .env files — "
            "delete that line.",
            fg="yellow",
            err=True,
        )


@cli.command()
@_env_file_option
def lock(file_path: str | None) -> None:
    """Remove the project's key from this machine."""
    path = _env_file_path(file_path)
    # Only the key this file names. Falling back to the ladder's id would let
    # `lock -f some-other-file` delete the project's key.
    key_id = _key_id_named_by(find_env_bindings(_read(path)))
    if not key_id:
        raise click.ClickException(f"{path} does not name a key ({ENV_KEY_ID_VAR}).")

    stored = stored_env_key_path(key_id)
    try:
        stored.unlink()
    except FileNotFoundError:
        click.echo(f"Key {key_id} is not on this machine")
        return
    click.echo(f"Removed key {key_id} from {stored}")


@cli.command()
@_env_file_option
def rotate(file_path: str | None) -> None:
    """Re-encrypt every value in the file under a new key, and store the new key.

    The old key stays on this machine, so branches that still name it keep
    loading.
    """
    path = _env_file_path(file_path)
    if not path.exists():
        raise click.ClickException(f"{path} does not exist")
    content = _read(path)
    bindings = find_env_bindings(content)

    # The id line governs the whole ladder, so values elsewhere in it would be
    # stranded under the old key. Rotate is one file at a time; say so.
    others = [
        other
        for other in dotenv_ladder(os.environ.get("PLAIN_ENV", ""))
        if Path(other) != path and _encrypted(find_env_bindings(_read(Path(other))))
    ]
    if others:
        raise click.ClickException(
            f"{', '.join(others)} also {'has' if len(others) == 1 else 'have'} "
            f"encrypted values under this key, and rotating {path} would leave them "
            "unreadable. Keep a project's encrypted values in one file before rotating."
        )

    old_key = _require_env_key(bindings)
    old_id = env_key_id(old_key)
    new_key = generate_env_key()
    new_id = env_key_id(new_key)

    file_flag = f" -f {file_path}" if file_path else ""
    encrypted = _encrypted(bindings)
    # Bindings come back in parse order, so rewriting from the end of the file
    # back keeps every earlier offset valid.
    for binding in reversed(encrypted):
        plaintext = _decrypt_or_fail(
            binding,
            env_key=old_key,
            problem=f"{binding.key} in {path} does not decrypt with key {old_id}. "
            f"Re-set it (`plain env set {binding.key}{file_flag}`) and rotate again.",
        )
        content = _replace_binding(
            content, binding, binding.key, encrypt_env_value(plaintext, new_key)
        )
    content = _with_binding(content, ENV_KEY_ID_VAR, new_id)

    stored = store_env_key(new_key)
    _write(path, content)

    click.echo(
        f"Re-encrypted {len(encrypted)} value{'s' if len(encrypted) != 1 else ''} "
        f"in {path} under key {new_id} (was {old_id})"
    )
    click.secho(
        f"The new key is in {stored}; update your team's copy. The old key stays on "
        "this machine so other branches still load. Rotating the key does not "
        "un-leak history — a leaked key means rotating the credentials themselves.",
        dim=True,
        err=True,
    )
    if env_key_from_environment() is not None:
        # The rotation can't update a key that came from the environment.
        click.secho(
            f"Warning: {ENV_KEY_VAR} in your environment still holds the old key. "
            "This machine will use the new key from its store, but update or unset "
            "the variable, and update it wherever else it is set.",
            fg="yellow",
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
    """
    _validate_name(name)
    path = _env_file_path(file_path)
    content = _read(path)
    env_key = _require_env_key(find_env_bindings(content))

    if value is None:
        if _stdin_is_a_tty():
            raise click.ClickException(
                "Pass VALUE as an argument, or pipe it in: plain env set NAME < file"
            )
        try:
            value = sys.stdin.read().removesuffix("\n")
        except UnicodeDecodeError as e:
            raise click.ClickException("VALUE is not valid UTF-8 text") from e

    token = encrypt_env_value(value, env_key)
    _write(path, _with_binding(content, name, token))
    click.echo(f"Wrote {name}={token} to {path}")

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
    bindings = find_env_bindings(_read(path), source=path)

    binding = next((b for b in bindings if b.key == name), None)
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

    click.echo(decrypt_env_binding(binding, env_key=_require_env_key(bindings)))


# --- the file ---


def _env_file_path(file_path: str | None) -> Path:
    return Path(file_path or f".env.{os.environ.get('PLAIN_ENV', 'dev')}")


def _read(path: Path) -> str:
    # newline="" keeps the file's line endings exactly as they are
    try:
        return path.read_text(encoding="utf-8", newline="")
    except FileNotFoundError:
        return ""


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="")


def _replace_binding(content: str, binding: Binding, name: str, value: str) -> str:
    """Content with `binding` rewritten as `name=value`, everything else byte for byte."""
    return (
        content[: binding.key_start] + f"{name}={value}" + content[binding.value_end :]
    )


def _with_binding(content: str, name: str, value: str) -> str:
    """Content with `name=value` in it: replacing the binding in place, or appended."""
    binding = find_env_binding(content, name)
    if binding:
        return _replace_binding(content, binding, name, value)

    line_ending = "\r\n" if "\r\n" in content else "\n"
    if content and not content.endswith("\n"):
        content += line_ending
    return content + f"{name}={value}" + line_ending


def _key_id_named_by(bindings: list[Binding]) -> str | None:
    """The key id the file names, if it has a PLAIN_ENV_KEY_ID line."""
    binding = next((b for b in bindings if b.key == ENV_KEY_ID_VAR), None)
    return binding.value if binding and binding.value else None


def _encrypted(bindings: list[Binding]) -> list[Binding]:
    return [b for b in bindings if b.encrypted]


# --- the key ---


def _require_env_key(bindings: list[Binding]) -> str:
    """The key for this file: by the id it names, else the id the ladder names."""
    ladder = loaded_directives()
    return resolve_env_key(
        env_key=env_key_from_environment(),
        key_line=key_line_of(ladder),
        key_id=_key_id_named_by(bindings) or named_key_id(ladder),
    )


def _decrypt_or_fail(binding: Binding, *, env_key: str, problem: str) -> str:
    """Decrypt one binding, or fail with `problem` — each command's own remedy."""
    try:
        return decrypt_env_binding(binding, env_key=env_key)
    except ImproperlyConfigured as e:
        raise click.ClickException(problem) from e


def _validate_name(name: str) -> None:
    if not _ENV_KEY_NAME_RE.fullmatch(name):
        raise click.ClickException(
            f"{name!r} is not a valid environment variable name "
            "(letters, digits and underscores, not starting with a digit)"
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
