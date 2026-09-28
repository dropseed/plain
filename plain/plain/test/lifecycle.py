"""
The extension point for the test runner (plain.testing).

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
    # "tests/test_signup.py::test_welcome", "...::TestInvites::test_expired",
    # or "...::test_price[annual]" for one case of a test with `@cases`.
    id: str
    # The names given to `@tag(...)`, the class's before the test's own.
    tags: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """The test's name within its file (e.g. "TestInvites::test_expired")."""
        return self.id.partition("::")[2]


class TestLifecycle:
    # When set, the lifecycle only loads if this package is in the app's
    # INSTALLED_PACKAGES — the entry point is importable whenever the package
    # is in the environment, which is a wider net than "the app uses it".
    required_package: str | None = None

    def setup_worker(self) -> None:
        """Called once per worker process, before any tests run."""

    def teardown_worker(self) -> None:
        """Called once per worker process, after all tests have run."""

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        """
        Wrap a single test. `test.tags` carries any `@tag(...)` labels, which
        lifecycles can use to vary behavior per-test.
        """
        yield
