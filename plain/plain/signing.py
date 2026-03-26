"""
URL-safe signed JSON objects using HMAC/SHA-256.

Use TimestampSigner for signing with expiration:

    TimestampSigner(salt="my-salt").sign_object({"key": "value"})
    TimestampSigner(salt="my-salt").unsign_object(token, max_age=3600)

Use Signer for signing without expiration:

    Signer(salt="my-salt").sign_object({"key": "value"})
    Signer(salt="my-salt").unsign_object(token)
"""

from __future__ import annotations

import base64
import datetime
import hmac
import json
import time
import zlib
from typing import Any

from plain.runtime import settings
from plain.utils.crypto import salted_hmac
from plain.utils.encoding import force_bytes
from plain.utils.regex_helper import _lazy_re_compile

_SEP_UNSAFE = _lazy_re_compile(r"^[A-z0-9-_=]*$")
BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class BadSignature(Exception):
    """Signature does not match."""

    pass


class SignatureExpired(BadSignature):
    """Signature timestamp is older than required max_age."""

    pass


def b62_encode(s: int) -> str:
    if s == 0:
        return "0"
    sign = "-" if s < 0 else ""
    s = abs(s)
    encoded = ""
    while s > 0:
        s, remainder = divmod(s, 62)
        encoded = BASE62_ALPHABET[remainder] + encoded
    return sign + encoded


def b62_decode(s: str) -> int:
    if s == "0":
        return 0
    sign = 1
    if s[0] == "-":
        s = s[1:]
        sign = -1
    decoded = 0
    for digit in s:
        decoded = decoded * 62 + BASE62_ALPHABET.index(digit)
    return sign * decoded


def b64_encode(s: bytes) -> bytes:
    return base64.urlsafe_b64encode(s).strip(b"=")


def b64_decode(s: bytes) -> bytes:
    pad = b"=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def base64_hmac(salt: str, value: str, key: str, algorithm: str = "sha1") -> str:
    return b64_encode(
        salted_hmac(salt, value, key, algorithm=algorithm).digest()
    ).decode()


class JSONSerializer:
    """
    Simple wrapper around json used by Signer.sign_object and
    Signer.unsign_object.
    """

    def dumps(self, obj: Any) -> bytes:
        return json.dumps(obj, separators=(",", ":")).encode("latin-1")

    def loads(self, data: bytes) -> Any:
        return json.loads(data.decode("latin-1"))


class Signer:
    def __init__(
        self,
        *,
        key: str | None = None,
        sep: str = ":",
        salt: str | None = None,
        algorithm: str = "sha256",
        fallback_keys: list[str] | None = None,
    ) -> None:
        self.key = key or settings.SECRET_KEY
        self.fallback_keys = (
            fallback_keys
            if fallback_keys is not None
            else settings.SECRET_KEY_FALLBACKS
        )
        self.sep = sep
        self.salt = salt or f"{self.__class__.__module__}.{self.__class__.__name__}"
        self.algorithm = algorithm

        if _SEP_UNSAFE.match(self.sep):
            raise ValueError(
                f"Unsafe Signer separator: {sep!r} (cannot be empty or consist of "
                "only A-z0-9-_=)",
            )

    def signature(self, value: str, key: str | None = None) -> str:
        key = key or self.key
        return base64_hmac(self.salt + "signer", value, key, algorithm=self.algorithm)

    def sign(self, value: str) -> str:
        return f"{value}{self.sep}{self.signature(value)}"

    def unsign(self, signed_value: str) -> str:
        if self.sep not in signed_value:
            raise BadSignature(f'No "{self.sep}" found in value')
        value, sig = signed_value.rsplit(self.sep, 1)
        for key in [self.key, *self.fallback_keys]:
            if hmac.compare_digest(
                force_bytes(sig), force_bytes(self.signature(value, key))
            ):
                return value
        raise BadSignature(f'Signature "{sig}" does not match')

    def sign_object(
        self,
        obj: Any,
        serializer: type[JSONSerializer] = JSONSerializer,
        compress: bool = False,
    ) -> str:
        """
        Return URL-safe, hmac signed base64 compressed JSON string.

        If compress is True (not the default), check if compressing using zlib
        can save some space. Prepend a '.' to signify compression. This is
        included in the signature, to protect against zip bombs.

        The serializer is expected to return a bytestring.
        """
        data = serializer().dumps(obj)
        # Flag for if it's been compressed or not.
        is_compressed = False

        if compress:
            # Avoid zlib dependency unless compress is being used.
            compressed = zlib.compress(data)
            if len(compressed) < (len(data) - 1):
                data = compressed
                is_compressed = True
        base64d = b64_encode(data).decode()
        if is_compressed:
            base64d = "." + base64d
        return self.sign(base64d)

    def unsign_object(
        self,
        signed_obj: str,
        serializer: type[JSONSerializer] = JSONSerializer,
        **kwargs: Any,
    ) -> Any:
        # Signer.unsign() returns str but base64 and zlib compression operate
        # on bytes.
        base64d = self.unsign(signed_obj, **kwargs).encode()
        decompress = base64d[:1] == b"."
        if decompress:
            # It's compressed; uncompress it first.
            base64d = base64d[1:]
        data = b64_decode(base64d)
        if decompress:
            data = zlib.decompress(data)
        return serializer().loads(data)


class TimestampSigner:
    """A signer that includes a timestamp for max_age validation.

    Uses composition rather than inheritance since the interface
    intentionally differs from Signer (unsign accepts max_age parameter).
    """

    def __init__(
        self,
        *,
        key: str | None = None,
        sep: str = ":",
        salt: str | None = None,
        algorithm: str = "sha256",
        fallback_keys: list[str] | None = None,
    ) -> None:
        # Compute default salt here to preserve backwards compatibility.
        # When TimestampSigner inherited from Signer, the default salt was
        # "plain.signing.TimestampSigner". Now that we use composition,
        # we must set it explicitly rather than letting Signer compute its own.
        if salt is None:
            salt = f"{self.__class__.__module__}.{self.__class__.__name__}"
        self._signer = Signer(
            key=key,
            sep=sep,
            salt=salt,
            algorithm=algorithm,
            fallback_keys=fallback_keys,
        )

    @property
    def sep(self) -> str:
        return self._signer.sep

    def timestamp(self) -> str:
        return b62_encode(int(time.time()))

    def sign(self, value: str) -> str:
        value = f"{value}{self.sep}{self.timestamp()}"
        return self._signer.sign(value)

    def unsign(
        self, value: str, max_age: int | float | datetime.timedelta | None = None
    ) -> str:
        """
        Retrieve original value and check it wasn't signed more
        than max_age seconds ago.
        """
        result = self._signer.unsign(value)
        value, timestamp = result.rsplit(self.sep, 1)
        ts = b62_decode(timestamp)
        if max_age is not None:
            if isinstance(max_age, datetime.timedelta):
                max_age = max_age.total_seconds()
            # Check timestamp is not older than max_age
            age = time.time() - ts
            if age > max_age:
                raise SignatureExpired(f"Signature age {age} > {max_age} seconds")
        return value

    def sign_object(
        self,
        obj: Any,
        serializer: type[JSONSerializer] = JSONSerializer,
        compress: bool = False,
    ) -> str:
        """
        Return URL-safe, hmac signed base64 compressed JSON string.

        If compress is True (not the default), check if compressing using zlib
        can save some space. Prepend a '.' to signify compression. This is
        included in the signature, to protect against zip bombs.

        The serializer is expected to return a bytestring.
        """
        data = serializer().dumps(obj)
        is_compressed = False

        if compress:
            compressed = zlib.compress(data)
            if len(compressed) < (len(data) - 1):
                data = compressed
                is_compressed = True
        base64d = b64_encode(data).decode()
        if is_compressed:
            base64d = "." + base64d
        return self.sign(base64d)

    def unsign_object(
        self,
        signed_obj: str,
        serializer: type[JSONSerializer] = JSONSerializer,
        max_age: int | float | datetime.timedelta | None = None,
    ) -> Any:
        """Unsign and decode an object, optionally checking max_age."""
        base64d = self.unsign(signed_obj, max_age=max_age).encode()
        decompress = base64d[:1] == b"."
        if decompress:
            base64d = base64d[1:]
        data = b64_decode(base64d)
        if decompress:
            data = zlib.decompress(data)
        return serializer().loads(data)
