"""`plain test` also runs where there is no app. The client can't work there,
and says so where it is created."""

from plain.packages import packages_registry
from plain.test import Client, patch, raises
from plain.test.exceptions import AppRequiredError


def test_client_without_an_app_says_what_it_needs() -> None:
    with patch(packages_registry, "ready", False), raises(AppRequiredError) as caught:
        Client()

    message = str(caught.exception)
    assert message.startswith("Client needs a Plain app")
    assert "run `plain test` from the directory that holds `app/`" in message


def test_client_with_an_app_is_created() -> None:
    assert Client().get("/").status_code == 200
