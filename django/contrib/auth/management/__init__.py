"""
Creates permissions for all installed apps that need permissions.
"""
import getpass
import unicodedata

from django.core import exceptions
from django.db import DEFAULT_DB_ALIAS


def get_system_username():
    """
    Return the current system user's username, or an empty string if the
    username could not be determined.
    """
    try:
        result = getpass.getuser()
    except (ImportError, KeyError):
        # KeyError will be raised by os.getpwuid() (called by getuser())
        # if there is no corresponding entry in the /etc/passwd file
        # (a very restricted chroot environment, for example).
        return ""
    return result


def get_default_username(check_db=True, database=DEFAULT_DB_ALIAS):
    """
    Try to determine the current system user's username to use as a default.

    :param check_db: If ``True``, requires that the username does not match an
        existing ``auth.User`` (otherwise returns an empty string).
    :param database: The database where the unique check will be performed.
    :returns: The username, or an empty string if no username can be
        determined or the suggested username is already taken.
    """
    # This file is used in apps.py, it should not trigger models import.
    from django.contrib.auth import models as auth_app

    # If the User model has been swapped out, we can't make any assumptions
    # about the default user name.
    if auth_app.User._meta.swapped:
        return ""

    default_username = get_system_username()
    try:
        default_username = (
            unicodedata.normalize("NFKD", default_username)
            .encode("ascii", "ignore")
            .decode("ascii")
            .replace(" ", "")
            .lower()
        )
    except UnicodeDecodeError:
        return ""

    # Run the username validator
    try:
        auth_app.User._meta.get_field("username").run_validators(default_username)
    except exceptions.ValidationError:
        return ""

    # Don't return the default username if it is already taken.
    if check_db and default_username:
        try:
            auth_app.User._default_manager.db_manager(database).get(
                username=default_username,
            )
        except auth_app.User.DoesNotExist:
            pass
        else:
            return ""
    return default_username
