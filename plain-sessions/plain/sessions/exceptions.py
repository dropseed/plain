from plain.exceptions import BadRequest, SuspiciousOperation


class SuspiciousSession(SuspiciousOperation):
    """The session may be tampered with"""

    pass


class SessionInterrupted(BadRequest):
    """The session was interrupted."""

    pass
