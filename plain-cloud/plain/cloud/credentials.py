"""Credential storage for the plain-cloud CLI.

Token in the OS keyring; api_url in a plain TOML file under ~/.plain/cloud/
(matching the ~/.plain/<package>/ layout established by plain-dev). Env vars
PLAIN_CLOUD_TOKEN and PLAIN_CLOUD_API_URL override stored values for
headless/CI use.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import click
import keyring
from keyring.errors import KeyringError, NoKeyringError

DEFAULT_API_URL = "https://plainframework.com"
SERVICE = "plain-cloud"


def config_path() -> Path:
    return Path.home() / ".plain" / "cloud" / "config.toml"


@dataclass
class Credentials:
    api_url: str
    token: str


class KeyringUnavailable(RuntimeError):
    """Raised when the OS keyring can't be reached and there's no env-var fallback."""


def _read_api_url() -> str | None:
    try:
        with config_path().open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return None
    return data.get("api_url") or None


def _write_api_url(api_url: str) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    escaped = api_url.replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(f'api_url = "{escaped}"\n')


def load() -> Credentials | None:
    if token := os.environ.get("PLAIN_CLOUD_TOKEN"):
        api_url = (
            os.environ.get("PLAIN_CLOUD_API_URL") or _read_api_url() or DEFAULT_API_URL
        )
        return Credentials(api_url=api_url, token=token)
    api_url = _read_api_url()
    if api_url is None:
        return None
    try:
        token = keyring.get_password(SERVICE, api_url)
    except KeyringError:
        return None
    if not token:
        return None
    return Credentials(api_url=api_url, token=token)


def save(creds: Credentials) -> str:
    """Persist credentials. Returns a human-readable description of where the token landed.

    Disk first, keyring second: if disk write fails we want no token in the keyring
    (orphaned secrets are worse than orphaned config — the latter is overwritten on
    the next successful login).
    """
    _write_api_url(creds.api_url)
    try:
        keyring.set_password(SERVICE, creds.api_url, creds.token)
    except NoKeyringError as exc:
        raise KeyringUnavailable(
            "No OS keyring backend available. "
            "Set PLAIN_CLOUD_TOKEN (and optionally PLAIN_CLOUD_API_URL) instead."
        ) from exc
    except KeyringError as exc:
        raise KeyringUnavailable(f"Keyring error: {exc}") from exc
    return keyring.get_keyring().name


def clear() -> bool:
    cleared = False
    api_url = _read_api_url()
    if api_url:
        try:
            keyring.delete_password(SERVICE, api_url)
            cleared = True
        except KeyringError:
            pass
    try:
        config_path().unlink()
        cleared = True
    except FileNotFoundError:
        pass
    return cleared


def require() -> Credentials:
    creds = load()
    if creds is None:
        click.secho(
            "Not logged in. Run `plain-cloud login` first.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    return creds
