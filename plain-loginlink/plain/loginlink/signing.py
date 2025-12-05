from __future__ import annotations

import time
import zlib
from typing import Any

from plain.signing import (
    JSONSerializer,
    SignatureExpired,
    Signer,
    b62_decode,
    b62_encode,
    b64_decode,
    b64_encode,
)


class ExpiringSigner:
    """A signer with an embedded expiration (vs max age unsign).

    Uses composition rather than inheritance since the interface
    intentionally differs from Signer (requires expires_in parameter).
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
        # When ExpiringSigner inherited from Signer, the default salt was
        # "plain.loginlink.signing.ExpiringSigner". Now that we use composition,
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

    def sign(self, value: str, expires_in: int) -> str:
        timestamp = b62_encode(int(time.time() + expires_in))
        value = f"{value}{self.sep}{timestamp}"
        return self._signer.sign(value)

    def unsign(self, signed_value: str) -> str:
        """
        Retrieve original value and check the expiration hasn't passed.
        """
        result = self._signer.unsign(signed_value)
        value, timestamp = result.rsplit(self.sep, 1)
        ts = b62_decode(timestamp)
        if ts < time.time():
            raise SignatureExpired("Signature expired")
        return value

    def sign_object(
        self,
        obj: Any,
        *,
        expires_in: int,
        serializer: type = JSONSerializer,
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
        return self.sign(base64d, expires_in)

    def unsign_object(self, signed_obj: str, serializer: type = JSONSerializer) -> Any:
        # Signer.unsign() returns str but base64 and zlib compression operate
        # on bytes.
        base64d = self.unsign(signed_obj).encode()
        decompress = base64d[:1] == b"."
        if decompress:
            # It's compressed; uncompress it first.
            base64d = base64d[1:]
        data = b64_decode(base64d)
        if decompress:
            data = zlib.decompress(data)
        return serializer().loads(data)


def dumps(
    obj: Any,
    *,
    expires_in: int,
    key: str | None = None,
    salt: str = "plain.loginlink",
    serializer: type = JSONSerializer,
    compress: bool = False,
) -> str:
    """
    Return URL-safe, hmac signed base64 compressed JSON string. If key is
    None, use settings.SECRET_KEY instead. The hmac algorithm is the default
    Signer algorithm.

    If compress is True (not the default), check if compressing using zlib can
    save some space. Prepend a '.' to signify compression. This is included
    in the signature, to protect against zip bombs.

    Salt can be used to namespace the hash, so that a signed string is
    only valid for a given namespace. Leaving this at the default
    value or re-using a salt value across different parts of your
    application without good cause is a security risk.

    The serializer is expected to return a bytestring.
    """
    return ExpiringSigner(key=key, salt=salt).sign_object(
        obj, expires_in=expires_in, serializer=serializer, compress=compress
    )


def loads(
    s: str,
    *,
    key: str | None = None,
    salt: str = "plain.loginlink",
    serializer: type = JSONSerializer,
    fallback_keys: list[str] | None = None,
) -> Any:
    """
    Reverse of dumps(), raise BadSignature if signature fails.

    The serializer is expected to accept a bytestring.
    """
    return ExpiringSigner(
        key=key, salt=salt, fallback_keys=fallback_keys
    ).unsign_object(
        s,
        serializer=serializer,
    )
