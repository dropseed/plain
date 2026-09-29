"""`plain request --user` logs the client in through plain.auth."""

from app.users.models import User
from click.testing import CliRunner
from plain.cli.core import cli
from plain.testing import override_settings


def test_request_as_a_user_is_that_users_request() -> None:
    user = User.query.create(username="ada")

    with override_settings(DEBUG=True):
        result = CliRunner().invoke(
            cli,
            ["request", "/whoami", "--user", str(user.id), "--no-headers"],
            prog_name="plain",
        )

    assert result.exit_code == 0, result.output
    assert "Status: 200" in result.output
    assert "User: " in result.output
    assert "ada" in result.output


def test_request_without_a_user_is_anonymous() -> None:
    with override_settings(DEBUG=True):
        result = CliRunner().invoke(
            cli, ["request", "/whoami", "--no-headers"], prog_name="plain"
        )

    # `plain request` follows redirects, and this one lands on the login page.
    assert "Redirected: /whoami → /login?next=/whoami (302)" in result.output
    assert "User: anonymous" in result.output
