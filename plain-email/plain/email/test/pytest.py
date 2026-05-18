"""Pytest fixtures for testing email — auto-registered via the ``pytest11`` entry point."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from plain.email.backends.locmem import outbox
from plain.runtime import settings

_LOCMEM_BACKEND = "plain.email.backends.locmem.EmailBackend"


@pytest.fixture
def mailoutbox() -> Generator[list]:
    """Email captured in memory for the duration of the test.

    Routes ``EMAIL_BACKEND`` to the in-memory backend and yields its
    ``outbox`` list (empty at the start of the test), restoring the
    original backend afterward.
    """
    original = settings.EMAIL_BACKEND
    settings.EMAIL_BACKEND = _LOCMEM_BACKEND
    outbox.clear()
    try:
        yield outbox
    finally:
        settings.EMAIL_BACKEND = original
        outbox.clear()
