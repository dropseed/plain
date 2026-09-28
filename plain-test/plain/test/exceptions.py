from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import ClientResponse

__all__ = ["AppRequiredError", "RedirectCycleError", "require_app"]


class RedirectCycleError(Exception):
    """The test client has been asked to follow a redirect loop."""

    def __init__(self, message: str, last_response: ClientResponse) -> None:
        super().__init__(message)
        self.last_response = last_response


class AppRequiredError(RuntimeError):
    """A test helper that needs a Plain app was used in a run without one."""


def require_app(helper: str) -> None:
    """Raise `AppRequiredError` unless a Plain app is set up.

    `helper` is the name to put in the message: `require_app("Client")`.
    """
    from plain.packages import packages_registry

    if packages_registry.ready:
        return

    raise AppRequiredError(
        f"{helper} needs a Plain app, and this run has none: there is no"
        " `app/` directory where `plain test` was started, so the tests are"
        " running on their own. That works for code that doesn't touch the"
        " app — `raises`, `@cases`, `@skip`, `@tag`, `skip_test`, `patch`,"
        " and bare `assert` all do. Anything that reads settings, routes or"
        f" the database does not. To use {helper}, run `plain test` from the"
        " directory that holds `app/`."
    )
