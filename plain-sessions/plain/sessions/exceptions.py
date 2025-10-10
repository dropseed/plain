from __future__ import annotations


class SessionNotAvailable(Exception):
    """
    Raised when attempting to access a session that hasn't been set up.

    This typically occurs when:
    - SessionMiddleware hasn't been called yet (e.g., during early middleware processing)
    - An error occurred before SessionMiddleware could run
    - A request is being processed outside the normal middleware chain
    """

    pass
