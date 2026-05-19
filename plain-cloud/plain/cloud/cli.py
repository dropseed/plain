"""Plain Cloud CLI.

Entrypoint for the `plain-cloud` binary. Subcommands authenticate against
a Plain Cloud installation using a personal API key minted from the
dashboard at /dashboard/api-keys/.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from pathlib import Path
from typing import BinaryIO

import click
import httpx
import keyring

from .client import Client
from .credentials import (
    DEFAULT_API_URL,
    Credentials,
    KeyringUnavailable,
    clear,
    config_path,
    load,
    require,
    save,
)


def _die(message: str, code: int = 1) -> None:
    click.secho(message, fg="red", err=True)
    sys.exit(code)


def _write_passthrough(text: str) -> None:
    if not text:
        return
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def _split_kv(s: str, sep: str, flag: str) -> tuple[str, str]:
    if sep not in s:
        _die(f"{flag} expected KEY{sep}VALUE, got {s!r}")
    key, _, value = s.partition(sep)
    return key, value


def _normalize_api_path(path: str) -> str:
    # Client.base_url already mounts /api. Strip a redundant leading
    # /api/ so users who copy from old docs (or the README's older
    # examples) still hit the right URL.
    stripped = path.lstrip("/")
    if stripped == "api" or stripped.startswith("api/"):
        stripped = stripped[3:].lstrip("/")
    return "/" + stripped


@click.group()
@click.version_option(package_name="plain.cloud", prog_name="plain-cloud")
def cli() -> None:
    """Manage your Plain Cloud account from the command line."""


@cli.command()
@click.option(
    "--api-url",
    default=DEFAULT_API_URL,
    show_default=True,
    envvar="PLAIN_CLOUD_API_URL",
    show_envvar=True,
    help="Base URL of the Plain Cloud API.",
)
@click.option(
    "--token",
    default=None,
    envvar="PLAIN_CLOUD_TOKEN",
    show_envvar=True,
    help="API token to save. If omitted, you'll be prompted.",
)
def login(api_url: str, token: str | None) -> None:
    """Save an API token for future commands.

    Mint a token at {api_url}/dashboard/api-keys/ and paste it here.
    """
    if token is None:
        click.echo(
            f"Mint a token at {api_url.rstrip('/')}/dashboard/api-keys/ and paste it below."
        )
        token = click.prompt("Token", hide_input=True).strip()
    if not token:
        _die("No token provided.")

    creds = Credentials(api_url=api_url, token=token)
    with Client(creds) as client:
        try:
            me = client.get("/me")
        except httpx.HTTPError as exc:
            _die(f"Could not reach {api_url}: {exc}")

    if not isinstance(me, dict):
        _die(
            f"Unexpected response from {api_url} when verifying the token. "
            "The token was not saved."
        )

    try:
        backend = save(creds)
    except KeyringUnavailable as exc:
        _die(str(exc))

    click.secho(
        f"Logged in as {me.get('email') or me.get('username') or 'unknown'}.",
        fg="green",
    )
    click.secho(f"Token stored in {backend}.", dim=True)


@cli.command()
def logout() -> None:
    """Forget the saved API token."""
    if clear():
        click.secho("Logged out.", fg="green")
    else:
        click.secho("No saved credentials.", dim=True)


@cli.command()
def whoami() -> None:
    """Show the user the current token belongs to."""
    creds = require()
    with Client(creds) as client:
        me = client.get("/me")
    if not isinstance(me, dict):
        # require() already caught a missing token, so we have credentials —
        # an empty/unexpected body here is a server-side problem, not logout.
        _die(
            f"Unexpected response from {creds.api_url} — could not read your identity.\n"
            "If this persists, re-authenticate with `plain-cloud login`."
        )
    if email := me.get("email"):
        identity = click.style(email, bold=True)
    else:
        identity = click.style("(no email)", dim=True)
    click.echo(f"{identity}  ·  {click.style(creds.api_url, dim=True)}")
    if me.get("username"):
        click.echo(f"username: {me['username']}")
    teams = me.get("teams") or []
    if teams:
        click.echo(f"teams: {len(teams)}")
        for team in teams:
            click.echo(
                f"  - {click.style(team['slug'], fg='cyan')} "
                f"{click.style('(' + team.get('role', '?') + ')', dim=True)}"
            )
    else:
        click.secho("teams: (none)", dim=True)


@cli.group()
def apps() -> None:
    """Manage Plain Cloud apps."""


@apps.command("list")
def apps_list() -> None:
    """List apps you have access to."""
    creds = require()
    with Client(creds) as client:
        data = client.get("/apps/")
    rows = data.get("apps") or []
    if not rows:
        click.secho("No apps yet.", dim=True)
        return
    width = max(len(row["slug"]) for row in rows)
    for row in rows:
        slug = click.style(f"{row['slug']:<{width}}", fg="cyan")
        team = click.style(row["team_slug"], dim=True)
        click.echo(f"  {slug}  {team}")


@cli.command("api")
@click.argument("path")
@click.option(
    "-X",
    "--method",
    default="GET",
    show_default=True,
    type=click.Choice(["GET", "POST", "PUT", "PATCH", "DELETE"], case_sensitive=False),
    help="HTTP method.",
)
@click.option(
    "-H",
    "--header",
    "headers",
    multiple=True,
    metavar="KEY:VALUE",
    help="Add a request header. Repeatable.",
)
@click.option(
    "-f",
    "--raw-field",
    "raw_fields",
    multiple=True,
    metavar="KEY=VALUE",
    help="Add a string field. Repeatable.",
)
@click.option(
    "-F",
    "--field",
    "typed_fields",
    multiple=True,
    metavar="KEY=VALUE",
    help=(
        "Add a typed field (true/false/null and numbers become JSON literals; "
        "@path reads a string from a file). Repeatable."
    ),
)
@click.option(
    "--input",
    "input_source",
    type=click.File("rb"),
    default=None,
    metavar="FILE",
    help='Read raw request body from FILE. Use "-" for stdin.',
)
@click.option(
    "--raw",
    is_flag=True,
    help="Print the response body verbatim, no JSON pretty-printing.",
)
def api(
    path: str,
    method: str,
    headers: tuple[str, ...],
    raw_fields: tuple[str, ...],
    typed_fields: tuple[str, ...],
    input_source: BinaryIO | None,
    raw: bool,
) -> None:
    """Call any Plain Cloud API path with the saved token.

    \b
    PATH is the API path as listed in `plain-cloud openapi` (e.g. /apps/).
    The /api/ prefix is added automatically; passing it explicitly also works.

    \b
    Fields go in the query string for GET requests and in the JSON body for
    everything else. Use -f for plain strings, -F for typed values
    (true/false/null/number, or @file to read a string from disk).

    \b
    Examples:
      plain-cloud api /me/
      plain-cloud api /apps/ -F page=2
      plain-cloud api /apps/foo/exceptions/123/resolve/ -X POST
      plain-cloud api /apps/ -X POST --input body.json -H "X-Trace: 1"

    Exit code is 0 for 2xx, 1 for everything else.
    """
    creds = require()
    method_upper = method.upper()
    path = _normalize_api_path(path)

    request_headers: dict[str, str] = {}
    for header in headers:
        key, value = _split_kv(header, ":", "--header")
        request_headers[key.strip()] = value.lstrip()

    fields: list[tuple[str, object]] = []
    for raw_field in raw_fields:
        key, value = _split_kv(raw_field, "=", "--raw-field")
        fields.append((key, value))
    for typed in typed_fields:
        key, value = _split_kv(typed, "=", "--field")
        fields.append((key, _coerce_field_value(value)))

    body_content = input_source.read() if input_source is not None else None

    request_kwargs: dict[str, object] = {}
    if request_headers:
        request_kwargs["headers"] = request_headers
    if body_content is not None:
        request_kwargs["content"] = body_content

    if fields:
        if body_content is None and method_upper != "GET":
            request_kwargs["json"] = dict(fields)
        else:
            request_kwargs["params"] = [(k, _to_query_value(v)) for k, v in fields]

    with Client(creds) as client:
        try:
            response = client.raw_request(method_upper, path, **request_kwargs)
        except httpx.HTTPError as exc:
            _die(f"Request failed: {exc}")

    if raw or not response.content:
        _write_passthrough(response.text)
    else:
        try:
            payload = response.json()
        except ValueError:
            _write_passthrough(response.text)
        else:
            click.echo(json.dumps(payload, indent=2))

    if response.status_code >= 400:
        click.secho(
            f"({method_upper} {path} → {response.status_code})",
            fg="red",
            err=True,
        )
        sys.exit(1)


def _coerce_field_value(value: str) -> object:
    # Mirrors `gh api -F` so users with gh muscle memory get the same coercion.
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if value.startswith("@"):
        try:
            return Path(value[1:]).read_text().rstrip("\n")
        except OSError as exc:
            _die(f"--field could not read {value[1:]}: {exc}")
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _to_query_value(value: object) -> str:
    # Lowercase true/false/null match `gh api`'s query rendering.
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


@cli.command("open")
@click.argument("path", required=False, default="/dashboard/")
@click.option(
    "--api-url",
    default=None,
    envvar="PLAIN_CLOUD_API_URL",
    show_envvar=True,
    help="Override the api_url (useful when not logged in).",
)
def open_url(path: str, api_url: str | None) -> None:
    """Open a Plain Cloud URL in your browser."""
    if api_url is None:
        creds = load()
        api_url = creds.api_url if creds else DEFAULT_API_URL
    base = api_url.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    url = base + path
    click.secho(f"Opening {url}", dim=True)
    webbrowser.open(url)


@cli.command("openapi")
@click.option(
    "--raw",
    is_flag=True,
    help="Print the response body verbatim, no JSON pretty-printing.",
)
@click.option(
    "--api-url",
    default=None,
    envvar="PLAIN_CLOUD_API_URL",
    show_envvar=True,
    help="Override the api_url (useful when not logged in).",
)
def openapi(raw: bool, api_url: str | None) -> None:
    """Fetch the OpenAPI document for this Plain Cloud install.

    The schema is metadata, so no token is required. When logged in, the
    saved api_url is used; pass --api-url to point elsewhere or to fetch
    without logging in.
    """
    if api_url is None:
        creds = load()
        api_url = creds.api_url if creds else DEFAULT_API_URL

    url = api_url.rstrip("/") + "/api/openapi.json"
    try:
        response = httpx.get(url, timeout=httpx.Timeout(30.0))
    except httpx.HTTPError as exc:
        _die(f"Could not reach {url}: {exc}")

    if response.status_code >= 400:
        _die(f"{response.status_code} fetching {url}: {response.text[:200]}")

    if raw:
        _write_passthrough(response.text)
        return
    try:
        click.echo(json.dumps(response.json(), indent=2, sort_keys=False))
    except ValueError:
        _write_passthrough(response.text)


@cli.command()
def config() -> None:
    """Show where credentials are stored."""
    creds = load()

    def row(label: str, value: str) -> None:
        click.echo(f"{click.style(label, bold=True)}  {value}")

    row("Config: ", str(config_path()))
    row("Keyring:", keyring.get_keyring().name)
    if creds:
        row("API:    ", creds.api_url)
        row("Status: ", click.style("logged in", fg="green"))
    else:
        row("Status: ", click.style("not logged in", dim=True))


if __name__ == "__main__":
    cli()
