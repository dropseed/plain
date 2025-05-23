"""
Functions for creating and restoring url-safe signed JSON objects.

The format used looks like this:

>>> signing.dumps("hello")
'ImhlbGxvIg:1QaUZC:YIye-ze3TTx7gtSv422nZA4sgmk'

There are two components here, separated by a ':'. The first component is a
URLsafe base64 encoded JSON of the object passed to dumps(). The second
component is a base64 encoded hmac/SHA-256 hash of "$first_component:$secret"

signing.loads(s) checks the signature and returns the deserialized object.
If the signature fails, a BadSignature exception is raised.

>>> signing.loads("ImhlbGxvIg:1QaUZC:YIye-ze3TTx7gtSv422nZA4sgmk")
'hello'
>>> signing.loads("ImhlbGxvIg:1QaUZC:YIye-ze3TTx7gtSv42-modified")
...
BadSignature: Signature "ImhlbGxvIg:1QaUZC:YIye-ze3TTx7gtSv42-modified" does not match

You can optionally compress the JSON prior to base64 encoding it to save
space, using the compress=True argument. This checks if compression actually
helps and only applies compression if the result is a shorter string:

>>> signing.dumps(list(range(1, 20)), compress=True)
'.eJwFwcERACAIwLCF-rCiILN47r-GyZVJsNgkxaFxoDgxcOHGxMKD_T7vhAml:1QaUaL:BA0thEZrp4FQVXIXuOvYJtLJSrQ'

The fact that the string is compressed is signalled by the prefixed '.' at the
start of the base64 JSON.

There are 65 url-safe characters: the 64 used by url-safe base64 and the ':'.
These functions make use of all of them.
"""

import base64
import datetime
import json
import time
import zlib

from plain.runtime import settings
from plain.utils.crypto import constant_time_compare, salted_hmac
from plain.utils.regex_helper import _lazy_re_compile

_SEP_UNSAFE = _lazy_re_compile(r"^[A-z0-9-_=]*$")
BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class BadSignature(Exception):
    """Signature does not match."""

    pass


class SignatureExpired(BadSignature):
    """Signature timestamp is older than required max_age."""

    pass


def b62_encode(s):
    if s == 0:
        return "0"
    sign = "-" if s < 0 else ""
    s = abs(s)
    encoded = ""
    while s > 0:
        s, remainder = divmod(s, 62)
        encoded = BASE62_ALPHABET[remainder] + encoded
    return sign + encoded


def b62_decode(s):
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


def b64_encode(s):
    return base64.urlsafe_b64encode(s).strip(b"=")


def b64_decode(s):
    pad = b"=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def base64_hmac(salt, value, key, algorithm="sha1"):
    return b64_encode(
        salted_hmac(salt, value, key, algorithm=algorithm).digest()
    ).decode()


class JSONSerializer:
    """
    Simple wrapper around json to be used in signing.dumps and
    signing.loads.
    """

    def dumps(self, obj):
        return json.dumps(obj, separators=(",", ":")).encode("latin-1")

    def loads(self, data):
        return json.loads(data.decode("latin-1"))


def dumps(
    obj, key=None, salt="plain.signing", serializer=JSONSerializer, compress=False
):
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
    return TimestampSigner(key=key, salt=salt).sign_object(
        obj, serializer=serializer, compress=compress
    )


def loads(
    s,
    key=None,
    salt="plain.signing",
    serializer=JSONSerializer,
    max_age=None,
    fallback_keys=None,
):
    """
    Reverse of dumps(), raise BadSignature if signature fails.

    The serializer is expected to accept a bytestring.
    """
    return TimestampSigner(
        key=key, salt=salt, fallback_keys=fallback_keys
    ).unsign_object(
        s,
        serializer=serializer,
        max_age=max_age,
    )


class Signer:
    def __init__(
        self,
        *,
        key=None,
        sep=":",
        salt=None,
        algorithm="sha256",
        fallback_keys=None,
    ):
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

    def signature(self, value, key=None):
        key = key or self.key
        return base64_hmac(self.salt + "signer", value, key, algorithm=self.algorithm)

    def sign(self, value):
        return f"{value}{self.sep}{self.signature(value)}"

    def unsign(self, signed_value):
        if self.sep not in signed_value:
            raise BadSignature(f'No "{self.sep}" found in value')
        value, sig = signed_value.rsplit(self.sep, 1)
        for key in [self.key, *self.fallback_keys]:
            if constant_time_compare(sig, self.signature(value, key)):
                return value
        raise BadSignature(f'Signature "{sig}" does not match')

    def sign_object(self, obj, serializer=JSONSerializer, compress=False):
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

    def unsign_object(self, signed_obj, serializer=JSONSerializer, **kwargs):
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


class TimestampSigner(Signer):
    def timestamp(self):
        return b62_encode(int(time.time()))

    def sign(self, value):
        value = f"{value}{self.sep}{self.timestamp()}"
        return super().sign(value)

    def unsign(self, value, max_age=None):
        """
        Retrieve original value and check it wasn't signed more
        than max_age seconds ago.
        """
        result = super().unsign(value)
        value, timestamp = result.rsplit(self.sep, 1)
        timestamp = b62_decode(timestamp)
        if max_age is not None:
            if isinstance(max_age, datetime.timedelta):
                max_age = max_age.total_seconds()
            # Check timestamp is not older than max_age
            age = time.time() - timestamp
            if age > max_age:
                raise SignatureExpired(f"Signature age {age} > {max_age} seconds")
        return value
