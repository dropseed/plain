import gzip
from functools import cached_property
from pathlib import Path

from plain.exceptions import (
    ValidationError,
)
from plain.utils.deconstruct import deconstructible
from plain.utils.text import pluralize


@deconstructible
class MinimumLengthValidator:
    """
    Validate that the password is of a minimum length.
    """

    def __init__(self, min_length=8):
        self.min_length = min_length

    def __call__(self, password):
        if len(password) < self.min_length:
            raise ValidationError(
                pluralize(
                    "This password is too short. It must contain at least "
                    "%(min_length)d character.",
                    "This password is too short. It must contain at least "
                    "%(min_length)d characters.",
                    self.min_length,
                ),
                code="password_too_short",
                params={"min_length": self.min_length},
            )


@deconstructible
class CommonPasswordValidator:
    """
    Validate that the password is not a common password.

    The password is rejected if it occurs in a provided list of passwords,
    which may be gzipped. The list Plain ships with contains 20000 common
    passwords (lowercased and deduplicated), created by Royce Williams:
    https://gist.github.com/roycewilliams/226886fd01572964e1431ac8afc999ce
    The password list must be lowercased to match the comparison in validate().
    """

    @cached_property
    def DEFAULT_PASSWORD_LIST_PATH(self):
        return Path(__file__).resolve().parent / "common-passwords.txt.gz"

    def __init__(self, password_list_path=DEFAULT_PASSWORD_LIST_PATH):
        if password_list_path is CommonPasswordValidator.DEFAULT_PASSWORD_LIST_PATH:
            password_list_path = self.DEFAULT_PASSWORD_LIST_PATH
        try:
            with gzip.open(password_list_path, "rt", encoding="utf-8") as f:
                self.passwords = {x.strip() for x in f}
        except OSError:
            with open(password_list_path) as f:
                self.passwords = {x.strip() for x in f}

    def __call__(self, password):
        if password.lower().strip() in self.passwords:
            raise ValidationError(
                "This password is too common.",
                code="password_too_common",
            )


@deconstructible
class NumericPasswordValidator:
    """
    Validate that the password is not entirely numeric.
    """

    def __call__(self, password):
        if password.isdigit():
            raise ValidationError(
                "This password is entirely numeric.",
                code="password_entirely_numeric",
            )
