from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import math
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings
from plain.utils.crypto import (
    RANDOM_STRING_CHARS,
    get_random_string,
    pbkdf2,
)
from plain.utils.encoding import force_bytes
from plain.utils.module_loading import import_string


def check_password(
    password: str,
    encoded: str,
    setter: Callable[[str], None] | None = None,
    preferred: str | BasePasswordHasher = "default",
) -> bool:
    """
    Return a boolean of whether the raw password matches the three
    part encoded digest.

    If setter is specified, it'll be called when you need to
    regenerate the password.
    """
    if not password:
        return False

    preferred = get_hasher(preferred)
    try:
        hasher = identify_hasher(encoded)
    except ValueError:
        # encoded is gibberish or uses a hasher that's no longer installed.
        return False

    hasher_changed = hasher.algorithm != preferred.algorithm
    must_update = hasher_changed or preferred.must_update(encoded)
    is_correct = hasher.verify(password, encoded)

    # If the hasher didn't change (we don't protect against enumeration if it
    # does) and the password should get updated, try to close the timing gap
    # between the work factor of the current encoded password and the default
    # work factor.
    if not is_correct and not hasher_changed and must_update:
        hasher.harden_runtime(password, encoded)

    if setter and is_correct and must_update:
        setter(password)
    return is_correct


def hash_password(
    password: str,
    salt: str | None = None,
    hasher: str | BasePasswordHasher = "default",
) -> str:
    """
    Turn a plain-text password into a hash for database storage

    Same as encode() but generate a new random salt. If password is None then
    return a concatenation of UNUSABLE_PASSWORD_PREFIX and a random string,
    which disallows logins. Additional random string reduces chances of gaining
    access to admin or superuser accounts. See ticket #20079 for more info.
    """
    hasher = get_hasher(hasher)
    salt = salt or hasher.salt()
    return hasher.encode(password, salt)


@functools.lru_cache
def get_hashers() -> list[BasePasswordHasher]:
    hashers = []
    for hasher_path in settings.PASSWORD_HASHERS:
        hasher_cls = import_string(hasher_path)
        hasher = hasher_cls()
        if not getattr(hasher, "algorithm"):
            raise ImproperlyConfigured(
                f"hasher doesn't specify an algorithm name: {hasher_path}"
            )
        hashers.append(hasher)
    return hashers


@functools.lru_cache
def get_hashers_by_algorithm() -> dict[str, BasePasswordHasher]:
    return {hasher.algorithm: hasher for hasher in get_hashers()}


def get_hasher(algorithm: str | BasePasswordHasher = "default") -> BasePasswordHasher:
    """
    Return an instance of a loaded password hasher.

    If algorithm is 'default', return the default hasher. Lazily import hashers
    specified in the project's settings file if needed.
    """
    if isinstance(algorithm, BasePasswordHasher):
        return algorithm

    elif algorithm == "default":
        return get_hashers()[0]

    else:
        hashers = get_hashers_by_algorithm()
        try:
            return hashers[algorithm]
        except KeyError:
            raise ValueError(
                f"Unknown password hashing algorithm '{algorithm}'. "
                "Did you specify it in the PASSWORD_HASHERS "
                "setting?"
            )


def identify_hasher(encoded: str) -> BasePasswordHasher:
    """
    Return an instance of a loaded password hasher.

    Identify hasher algorithm by examining encoded hash, and call
    get_hasher() to return hasher. Raise ValueError if
    algorithm cannot be identified, or if hasher is not loaded.
    """
    # Ancient versions of Plain created plain MD5 passwords and accepted
    # MD5 passwords with an empty salt.
    if (len(encoded) == 32 and "$" not in encoded) or (
        len(encoded) == 37 and encoded.startswith("md5$$")
    ):
        algorithm = "unsalted_md5"
    # Ancient versions of Plain accepted SHA1 passwords with an empty salt.
    elif len(encoded) == 46 and encoded.startswith("sha1$$"):
        algorithm = "unsalted_sha1"
    else:
        algorithm = encoded.split("$", 1)[0]
    return get_hasher(algorithm)


def mask_hash(hash: str, show: int = 6, char: str = "*") -> str:
    """
    Return the given hash, with only the first ``show`` number shown. The
    rest are masked with ``char`` for security reasons.
    """
    masked = hash[:show]
    masked += char * len(hash[show:])
    return masked


def must_update_salt(salt: str, expected_entropy: int) -> bool:
    # Each character in the salt provides log_2(len(alphabet)) bits of entropy.
    return len(salt) * math.log2(len(RANDOM_STRING_CHARS)) < expected_entropy


class BasePasswordHasher(ABC):
    """
    Abstract base class for password hashers

    When creating your own hasher, you need to override algorithm,
    verify(), encode() and safe_summary().

    PasswordHasher objects are immutable.
    """

    algorithm: str | None = None
    salt_entropy: int = 128

    def salt(self) -> str:
        """
        Generate a cryptographically secure nonce salt in ASCII with an entropy
        of at least `salt_entropy` bits.
        """
        # Each character in the salt provides
        # log_2(len(alphabet)) bits of entropy.
        char_count = math.ceil(self.salt_entropy / math.log2(len(RANDOM_STRING_CHARS)))
        return get_random_string(char_count, allowed_chars=RANDOM_STRING_CHARS)

    @abstractmethod
    def verify(self, password: str, encoded: str) -> bool:
        """Check if the given password is correct."""
        ...

    def _check_encode_args(self, password: str, salt: str) -> None:
        if password is None:
            raise TypeError("password must be provided.")
        if not salt or "$" in salt:
            raise ValueError("salt must be provided and cannot contain $.")

    @abstractmethod
    def encode(self, password: str, salt: str) -> str:
        """
        Create an encoded database value.

        The result is normally formatted as "algorithm$salt$hash" and
        must be fewer than 128 characters.
        """
        ...

    @abstractmethod
    def decode(self, encoded: str) -> dict[str, Any]:
        """
        Return a decoded database value.

        The result is a dictionary and should contain `algorithm`, `hash`, and
        `salt`. Extra keys can be algorithm specific like `iterations` or
        `work_factor`.
        """
        ...

    @abstractmethod
    def safe_summary(self, encoded: str) -> dict[str, Any]:
        """
        Return a summary of safe values.

        The result is a dictionary and will be used where the password field
        must be displayed to construct a safe representation of the password.
        """
        ...

    def must_update(self, encoded: str) -> bool:
        return False

    def harden_runtime(self, password: str, encoded: str) -> None:
        """
        Bridge the runtime gap between the work factor supplied in `encoded`
        and the work factor suggested by this hasher.

        Taking PBKDF2 as an example, if `encoded` contains 20000 iterations and
        `self.iterations` is 30000, this method should run password through
        another 10000 iterations of PBKDF2. Similar approaches should exist
        for any hasher that has a work factor. If not, this method should be
        defined as a no-op to silence the warning.
        """
        warnings.warn(
            "subclasses of BasePasswordHasher should provide a harden_runtime() method"
        )


class PBKDF2PasswordHasher(BasePasswordHasher):
    """
    Secure password hashing using the PBKDF2 algorithm (recommended)

    Configured to use PBKDF2 + HMAC + SHA256.
    The result is a 64 byte binary string.  Iterations may be changed
    safely but you must rename the algorithm if you change SHA256.
    """

    algorithm = "pbkdf2_sha256"
    iterations = 720000
    digest = hashlib.sha256

    def encode(self, password: str, salt: str, iterations: int | None = None) -> str:
        self._check_encode_args(password, salt)
        iterations = iterations or self.iterations
        hash = pbkdf2(password, salt, iterations, digest=self.digest)
        hash = base64.b64encode(hash).decode("ascii").strip()
        return "%s$%d$%s$%s" % (self.algorithm, iterations, salt, hash)  # noqa: UP031

    def decode(self, encoded: str) -> dict[str, Any]:
        algorithm, iterations, salt, hash = encoded.split("$", 3)
        assert algorithm == self.algorithm
        return {
            "algorithm": algorithm,
            "hash": hash,
            "iterations": int(iterations),
            "salt": salt,
        }

    def verify(self, password: str, encoded: str) -> bool:
        decoded = self.decode(encoded)
        encoded_2 = self.encode(password, decoded["salt"], decoded["iterations"])
        return hmac.compare_digest(force_bytes(encoded), force_bytes(encoded_2))

    def safe_summary(self, encoded: str) -> dict[str, Any]:
        decoded = self.decode(encoded)
        return {
            "algorithm": decoded["algorithm"],
            "iterations": decoded["iterations"],
            "salt": mask_hash(decoded["salt"]),
            "hash": mask_hash(decoded["hash"]),
        }

    def must_update(self, encoded: str) -> bool:
        decoded = self.decode(encoded)
        update_salt = must_update_salt(decoded["salt"], self.salt_entropy)
        return (decoded["iterations"] != self.iterations) or update_salt

    def harden_runtime(self, password: str, encoded: str) -> None:
        decoded = self.decode(encoded)
        extra_iterations = self.iterations - decoded["iterations"]
        if extra_iterations > 0:
            self.encode(password, decoded["salt"], extra_iterations)
