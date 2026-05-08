from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from click.testing import CliRunner

from plain.cloud import cli as cli_module
from plain.cloud.cli import cli
from plain.cloud.client import Client
from plain.cloud.credentials import SERVICE, Credentials, save


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_api(
    monkeypatch,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], None]:
    """Install a MockTransport so CLI commands hit a fake API."""

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        transport = httpx.MockTransport(handler)

        def make_client(creds: Credentials) -> Client:
            return Client(creds, transport=transport)

        monkeypatch.setattr(cli_module, "Client", make_client)

    return install


def test_help_runs(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Manage your Plain Cloud account" in result.output


def test_whoami_without_login_exits_with_error(runner):
    result = runner.invoke(cli, ["whoami"])
    assert result.exit_code == 1
    assert "Not logged in" in result.output


def test_login_validates_token_and_persists(runner, mock_api, fake_keyring):
    mock_api(lambda req: httpx.Response(200, json={"email": "user@example.com"}))

    result = runner.invoke(
        cli,
        ["login", "--api-url", "https://example.com", "--token", "good-token"],
    )

    assert result.exit_code == 0, result.output
    assert "Logged in as user@example.com" in result.output
    assert fake_keyring.get_password(SERVICE, "https://example.com") == "good-token"


def test_login_rejects_bad_token(runner, mock_api, fake_keyring):
    mock_api(lambda req: httpx.Response(401, json={"error": "invalid token"}))

    result = runner.invoke(
        cli,
        ["login", "--api-url", "https://example.com", "--token", "bad"],
    )

    assert result.exit_code == 1
    assert "invalid token" in result.output
    # Bad token must not get saved.
    assert fake_keyring.get_password(SERVICE, "https://example.com") is None


def test_whoami_after_login(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    mock_api(
        lambda req: httpx.Response(
            200,
            json={
                "email": "user@example.com",
                "username": "user",
                "teams": [{"slug": "acme", "role": "owner"}],
            },
        )
    )

    result = runner.invoke(cli, ["whoami"])

    assert result.exit_code == 0, result.output
    assert "user@example.com" in result.output
    assert "acme" in result.output


def test_apps_list_empty(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    mock_api(lambda req: httpx.Response(200, json={"apps": []}))

    result = runner.invoke(cli, ["apps", "list"])

    assert result.exit_code == 0
    assert "No apps yet" in result.output


def test_apps_list_renders_rows(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    mock_api(
        lambda req: httpx.Response(
            200,
            json={
                "apps": [
                    {"slug": "web", "team_slug": "acme"},
                    {"slug": "worker", "team_slug": "acme"},
                ]
            },
        )
    )

    result = runner.invoke(cli, ["apps", "list"])

    assert result.exit_code == 0
    assert "web" in result.output
    assert "worker" in result.output
    assert "acme" in result.output


def test_logout_after_login(runner):
    save(Credentials(api_url="https://example.com", token="tok"))

    result = runner.invoke(cli, ["logout"])

    assert result.exit_code == 0
    assert "Logged out" in result.output


def test_logout_when_not_logged_in(runner):
    result = runner.invoke(cli, ["logout"])
    assert result.exit_code == 0
    assert "No saved credentials" in result.output


def test_config_when_logged_out(runner):
    result = runner.invoke(cli, ["config"])
    assert result.exit_code == 0
    assert "not logged in" in result.output


def test_config_when_logged_in(runner):
    save(Credentials(api_url="https://example.com", token="tok"))

    result = runner.invoke(cli, ["config"])

    assert result.exit_code == 0
    assert "https://example.com" in result.output
    assert "logged in" in result.output


def test_open_uses_stored_api_url(runner, monkeypatch):
    save(Credentials(api_url="https://example.com", token="tok"))
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    result = runner.invoke(cli, ["open"])

    assert result.exit_code == 0
    assert opened == ["https://example.com/dashboard/"]


def test_open_with_path(runner, monkeypatch):
    save(Credentials(api_url="https://example.com", token="tok"))
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    result = runner.invoke(cli, ["open", "/teams/"])

    assert result.exit_code == 0
    assert opened == ["https://example.com/teams/"]


def _capture(into: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        into.append(req)
        return httpx.Response(200, json={"ok": True})

    return handler


def test_api_get_routes_fields_to_query_string(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))

    result = runner.invoke(
        cli, ["api", "/api/apps/", "-F", "page=2", "-F", "active=true"]
    )

    assert result.exit_code == 0, result.output
    req = captured[0]
    assert req.method == "GET"
    assert req.url.params["page"] == "2"
    assert req.url.params["active"] == "true"


def test_api_path_accepts_both_with_and_without_api_prefix(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))

    result = runner.invoke(cli, ["api", "/apps/"])
    assert result.exit_code == 0, result.output
    assert captured[0].url.path == "/api/apps/"

    result = runner.invoke(cli, ["api", "/api/apps/"])
    assert result.exit_code == 0, result.output
    assert captured[1].url.path == "/api/apps/"


def test_api_post_routes_typed_and_raw_fields_to_json_body(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))

    result = runner.invoke(
        cli,
        [
            "api",
            "/api/apps/foo/",
            "-X",
            "POST",
            "-F",
            "count=42",
            "-F",
            "active=true",
            "-f",
            "name=foo",
        ],
    )

    assert result.exit_code == 0, result.output
    req = captured[0]
    assert req.method == "POST"
    body = json.loads(req.content)
    assert body == {"count": 42, "active": True, "name": "foo"}


def test_api_input_file_provides_raw_body(runner, mock_api, tmp_path):
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))
    body_file = tmp_path / "body.json"
    body_file.write_text('{"hello":"world"}')

    result = runner.invoke(
        cli, ["api", "/api/apps/", "-X", "POST", "--input", str(body_file)]
    )

    assert result.exit_code == 0, result.output
    assert captured[0].content == b'{"hello":"world"}'


def test_api_input_with_fields_pushes_fields_to_query(runner, mock_api, tmp_path):
    """When --input occupies the body slot, fields fall through to the query string."""
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))
    body_file = tmp_path / "body.json"
    body_file.write_text('{"hello":"world"}')

    result = runner.invoke(
        cli,
        [
            "api",
            "/api/apps/",
            "-X",
            "POST",
            "--input",
            str(body_file),
            "-F",
            "page=2",
        ],
    )

    assert result.exit_code == 0, result.output
    req = captured[0]
    assert req.content == b'{"hello":"world"}'
    assert req.url.params["page"] == "2"


def test_api_header_is_sent(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))

    result = runner.invoke(cli, ["api", "/api/apps/", "-H", "X-Trace: abc123"])

    assert result.exit_code == 0, result.output
    assert captured[0].headers.get("x-trace") == "abc123"


def test_api_field_at_file_reads_string_from_disk(runner, mock_api, tmp_path):
    save(Credentials(api_url="https://example.com", token="tok"))
    captured: list[httpx.Request] = []
    mock_api(_capture(captured))
    note_file = tmp_path / "note.txt"
    note_file.write_text("hello from disk\n")

    result = runner.invoke(
        cli, ["api", "/api/apps/", "-X", "POST", "-F", f"note=@{note_file}"]
    )

    assert result.exit_code == 0, result.output
    body = json.loads(captured[0].content)
    assert body == {"note": "hello from disk"}


def test_api_non_2xx_exits_1(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    mock_api(lambda req: httpx.Response(404, json={"error": "not found"}))

    result = runner.invoke(cli, ["api", "/api/missing/"])

    assert result.exit_code == 1


def test_api_invalid_header_format(runner, mock_api):
    save(Credentials(api_url="https://example.com", token="tok"))
    mock_api(lambda req: httpx.Response(200))

    result = runner.invoke(cli, ["api", "/api/apps/", "-H", "no-colon-here"])

    assert result.exit_code == 1
    assert "expected KEY:VALUE" in result.output
