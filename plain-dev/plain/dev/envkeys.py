"""Custody of a project's env key: its id, this machine's store, and resolution.

Encrypted values in a committed `.env` file are unlocked by one symmetric key
per project. The key never lives in a working tree. It lives on each machine
in `~/.plain/env-keys/<id>`, named by a short fingerprint, and the file names
it with a plain `PLAIN_ENV_KEY_ID=<id>` line. Where there is no machine store
(a sandbox, CI), `PLAIN_ENV_KEY` in the environment carries the key instead.

The loader (`plain.dev.dotenv`) and the `plain env` commands both come here to
turn "what the files name" and "what the environment supplied" into one key.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from plain.exceptions import ImproperlyConfigured

# The key, when the environment supplies it. The loader takes it out of the
# environment on load and keeps it in memory: nothing under the loader needs
# it, so nothing under the loader can read it.
ENV_KEY_VAR = "PLAIN_ENV_KEY"
# The line in a `.env` file naming the key it was encrypted with, by id.
ENV_KEY_ID_VAR = "PLAIN_ENV_KEY_ID"
# What the first version called the key. Only ever seen as a leftover line.
LEGACY_ENV_KEY_VAR = "DEV_ENV_KEY"

# Lines a `.env` file can carry that speak to the loader rather than the app.
# None of them is ever bound as a variable: the id is a pointer, and the key
# lines are secrets that no other value may capture.
KEY_LINE_NAMES = (ENV_KEY_VAR, LEGACY_ENV_KEY_VAR)
DIRECTIVE_NAMES = frozenset({ENV_KEY_ID_VAR, *KEY_LINE_NAMES})

# Where this machine keeps the keys it has been given: one file per key, named
# by the key's id. Outside every checkout, so a clone, a worktree and a fork of
# a project all find the same key, and a working tree never holds a secret.
# Not under the cache path: a cache is something you can delete, a key is not.
ENV_KEYS_PATH = Path.home() / ".plain" / "env-keys"

# The id is written into committed files and names a file in the store, so its
# length is a wire format: the digest slice, the pattern that validates it and
# the error message that describes it all read it from here.
_ENV_KEY_ID_LENGTH = 12
_ENV_KEY_ID_RE = re.compile(rf"^[0-9a-f]{{{_ENV_KEY_ID_LENGTH}}}$")

# Said by the loader and by `plain env unlock`, about the same rule.
INVALID_ENV_KEY_HINT = (
    "is not a valid key (expected the 44 character key written by `plain env init`)"
)


# --- keys and ids ---


def generate_env_key() -> str:
    """Generate a new key (a Fernet key: urlsafe base64, 44 chars)."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def is_valid_env_key(env_key: str) -> bool:
    """True when `env_key` is in the form `generate_env_key` produces."""
    from cryptography.fernet import Fernet

    try:
        Fernet(env_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False
    return True


def env_key_id(env_key: str) -> str:
    """The id a file names its key by: `PLAIN_ENV_KEY_ID=<id>`."""
    return hashlib.sha256(env_key.encode("ascii")).hexdigest()[:_ENV_KEY_ID_LENGTH]


def check_env_key_id(key_id: str) -> None:
    """Raise ImproperlyConfigured unless `key_id` is in the form `env_key_id` produces.

    The id comes from a committed file and names a file in the store, so it is
    checked before it is ever joined to a path — and the offending value is not
    repeated back, since `$VAR` expansion could have put a secret in it.
    """
    if not _ENV_KEY_ID_RE.fullmatch(key_id):
        raise ImproperlyConfigured(
            f"{ENV_KEY_ID_VAR} is not a key id ({_ENV_KEY_ID_LENGTH} hex characters, "
            "as written by `plain env init`)."
        )


# --- this machine's store ---


def stored_env_key_path(key_id: str) -> Path:
    """Where this machine keeps the key with this id, whether or not it has it."""
    check_env_key_id(key_id)
    return ENV_KEYS_PATH / key_id


def store_env_key(env_key: str) -> Path:
    """Save a key to this machine's store, readable by this user only, and return its path.

    The directory and the file are made private even if they already existed
    with looser permissions, and a symlink in either place is refused rather
    than followed.
    """
    path = stored_env_key_path(env_key_id(env_key))
    if path.parent.is_symlink():
        raise ImproperlyConfigured(
            f"{path.parent} is a symlink; the key store must be a real directory."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise ImproperlyConfigured(
            f"Could not write the key to {path}: {e.strerror}. If it is a symlink, "
            "remove it; the store holds plain files only."
        ) from e
    with os.fdopen(fd, "w", encoding="ascii") as f:
        os.fchmod(fd, 0o600)
        f.write(env_key + "\n")
    return path


def read_stored_env_key(key_id: str) -> str | None:
    """The stored key with this id, or None if this machine doesn't have it.

    A store file that can't be read or doesn't hold a key is reported as the
    store's problem, not blamed on the `.env` file it fails to decrypt.
    """
    path = stored_env_key_path(key_id)
    try:
        env_key = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise ImproperlyConfigured(
            f"Could not read the key stored at {path}: {e}. Remove it and run "
            "`plain env unlock` again."
        ) from e
    if not is_valid_env_key(env_key):
        raise ImproperlyConfigured(
            f"The key stored at {path} {INVALID_ENV_KEY_HINT}. Remove it and run "
            "`plain env unlock` again."
        )
    return env_key


# --- resolution ---


def resolve_env_key(
    *,
    env_key: str | None,
    key_line: tuple[str, str] | None,
    key_id: str | None,
    about: str = "",
) -> str:
    """The key that decrypts these values, or ImproperlyConfigured saying what to do.

    The key on offer is `env_key` (from the environment) or, failing that,
    `key_line` (a `NAME=value` key line from a file, as a pair). When the files
    name an id, the key has to be that one: the offered key if its id matches,
    else this machine's store. With no id, the offered key is used as-is.
    `about` prefixes the message with what was being decrypted.
    """
    if env_key is not None:
        offered: str | None = env_key
        source = f"{ENV_KEY_VAR} in the environment"
    elif key_line is not None:
        offered = key_line[1]
        source = f"the {key_line[0]}= line"
    else:
        offered = None
        source = ""

    if offered is not None and not is_valid_env_key(offered):
        # Empty, a leftover `$(...)` line and a mistyped paste all fail the same
        # test; they differ only in what the developer needs to be told. None of
        # the messages repeat the value: it is meant to be a secret.
        if offered.startswith("$("):
            raise ImproperlyConfigured(
                f"{about}{source} is a $(...) command, and commands no longer run "
                "in .env files. Run that command yourself and pipe its output "
                "into `plain env unlock`, which stores the key on this machine "
                f"and replaces the line with {ENV_KEY_ID_VAR}."
            )
        if not offered:
            raise ImproperlyConfigured(f"{about}{source} is set to an empty value.")
        raise ImproperlyConfigured(f"{source} {INVALID_ENV_KEY_HINT}.")

    if key_id:
        offered_id = env_key_id(offered) if offered is not None else None
        if offered is not None and offered_id == key_id:
            return offered
        stored = read_stored_env_key(key_id)
        if stored is not None:
            return stored
        if offered_id is not None:
            raise ImproperlyConfigured(
                f"{source} is key {offered_id}, but {ENV_KEY_ID_VAR} names key "
                f"{key_id}: it is not the key these values were encrypted with."
            )
        raise ImproperlyConfigured(
            f"{about}key {key_id} is not on this machine. Get this project's key "
            "from wherever your team keeps it and pipe it into `plain env unlock`, "
            f"or set {ENV_KEY_VAR} in the environment."
        )

    if offered is not None:
        return offered

    raise ImproperlyConfigured(
        f"{about}no key is available: {ENV_KEY_VAR} is not set and no file names "
        f"one with {ENV_KEY_ID_VAR}. For a new project run `plain env init`; for an "
        "existing one, get its key and pipe it into `plain env unlock`."
    )
