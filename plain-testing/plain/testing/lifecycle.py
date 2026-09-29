"""
The extension point for the test runner.

Packages that participate in testing subclass TestLifecycle and register it
under the `plain.testing` entry point group:

    [project.entry-points."plain.testing"]
    postgres = "plain.postgres.test.lifecycle:PostgresTestLifecycle"

The runner discovers and drives lifecycles; packages never import the runner.
"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

__all__ = ["CollectedTest", "TestLifecycle"]


@dataclass(frozen=True, kw_only=True)
class CollectedTest:
    """
    One test the runner is about to run, as `around_test(test)` receives it.
    """

    # Where the test is and what it is called, as the runner prints it:
    # "tests/test_signup.py::test_welcome", or "...::test_price[annual]" for
    # one case of a test with `@cases`.
    id: str
    # The names given to `@tag(...)`.
    tags: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """The test's name within its file (e.g. "test_price[annual]")."""
        return self.id.partition("::")[2]


class TestLifecycle:
    # When set, the lifecycle only loads if this package is in the app's
    # INSTALLED_PACKAGES — the entry point is importable whenever the package
    # is in the environment, which is a wider net than "the app uses it".
    required_package: str | None = None

    def setup_worker(self) -> None:
        """Called once per run, before the first test."""

    def teardown_worker(self) -> None:
        """Called once per run, after the last test."""

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        """
        Wrap a single test. `test.tags` carries any `@tag(...)` labels, which
        lifecycles can use to vary behavior per-test.
        """
        yield

    def describe_value(self, value: object) -> str | None:
        """
        What a failure report prints for a value this package owns, or None
        for a value that isn't this package's to describe.

        A report prints the values a failed test had in hand, by their
        `repr`. This is for a value whose `repr` says too little to fix a
        test by (a model instance that prints as its class and its id).
        The text is printed as it is, on one line or several.

        It is called while the test's lifecycles are still in place. It
        must not change anything the test did, and must not do anything the
        test didn't: a description that runs a query is a query the failing
        test never ran.
        """
        return None
