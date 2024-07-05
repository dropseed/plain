import fnmatch
import os

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings


def matches_patterns(path, patterns):
    """
    Return True or False depending on whether the ``path`` should be
    ignored (if it matches any pattern in ``ignore_patterns``).
    """
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def get_files(storage, ignore_patterns=None, location=""):
    """
    Recursively walk the storage directories yielding the paths
    of all files that should be copied.
    """
    if ignore_patterns is None:
        ignore_patterns = []
    directories, files = storage.listdir(location)
    for fn in files:
        # Match only the basename.
        if matches_patterns(fn, ignore_patterns):
            continue
        if location:
            fn = os.path.join(location, fn)
            # Match the full file path.
            if matches_patterns(fn, ignore_patterns):
                continue
        yield fn
    for dir in directories:
        if matches_patterns(dir, ignore_patterns):
            continue
        if location:
            dir = os.path.join(location, dir)
        yield from get_files(storage, ignore_patterns, dir)


def check_settings(base_url=None):
    """
    Check if the assets settings have sane values.
    """
    if base_url is None:
        base_url = settings.ASSETS_URL
    if not base_url:
        raise ImproperlyConfigured(
            "You're using the assets app "
            "without having set the required ASSETS_URL setting."
        )
