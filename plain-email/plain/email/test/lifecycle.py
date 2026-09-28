"""
Email test lifecycle, registered under the `plain.test` entry point.

Routes EMAIL_BACKEND to the in-memory backend for the whole run — tests
never send real email — and clears the outbox before each test.
"""

from collections.abc import Generator
from contextlib import ExitStack, contextmanager

from plain.test import CollectedTest, TestLifecycle, override_settings

from ..backends.locmem import outbox

_LOCMEM_BACKEND = "plain.email.backends.locmem.EmailBackend"


class EmailTestLifecycle(TestLifecycle):
    required_package = "plain.email"

    def __init__(self) -> None:
        # Holds the setting overridden from setup to teardown.
        self._in_memory_backend = ExitStack()

    def setup_worker(self) -> None:
        self._in_memory_backend.enter_context(
            override_settings(EMAIL_BACKEND=_LOCMEM_BACKEND)
        )

    def teardown_worker(self) -> None:
        self._in_memory_backend.close()

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        outbox.clear()
        yield
