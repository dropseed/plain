#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

# We don't need to call super() in __init__ methods of our
# BaseException and Exception classes because we also define
# our own __str__ methods so there is no need to pass 'message'
# to the base class to get a meaningful output from 'str(exc)'.
# pylint: disable=super-init-not-called


# we inherit from BaseException here to make sure to not be caught
# at application level
class HaltServer(BaseException):
    def __init__(self, reason: str, exit_status: int = 1) -> None:
        self.reason = reason
        self.exit_status = exit_status

    def __str__(self) -> str:
        return f"<HaltServer {self.reason!r} {self.exit_status}>"


class ConfigError(Exception):
    """Exception raised on config error"""


class AppImportError(Exception):
    """Exception raised when loading an application"""
