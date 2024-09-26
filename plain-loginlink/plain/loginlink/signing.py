import time
import zlib

from plain.signing import (
    JSONSerializer,
    SignatureExpired,
    Signer,
    b62_decode,
    b62_encode,
    b64_decode,
    b64_encode,
)


class ExpiringSigner(Signer):
    """A signer with an embedded expiration (vs max age unsign)"""

    def sign(self, value, expires_in):
        timestamp = b62_encode(int(time.time() + expires_in))
        value = f"{value}{self.sep}{timestamp}"
        return super().sign(value)

    def unsign(self, value):
        """
        Retrieve original value and check the expiration hasn't passed.
        """
        result = super().unsign(value)
        value, timestamp = result.rsplit(self.sep, 1)
        timestamp = b62_decode(timestamp)
        if timestamp < time.time():
            raise SignatureExpired("Signature expired")
        return value

    def sign_object(
        self, obj, serializer=JSONSerializer, compress=False, expires_in=None
    ):
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

    def unsign_object(self, signed_obj, serializer=JSONSerializer):
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
    obj,
    key=None,
    salt="plain.loginlink",
    serializer=JSONSerializer,
    compress=False,
    expires_in=None,
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
    return ExpiringSigner(key=key, salt=salt).sign_object(
        obj, serializer=serializer, compress=compress, expires_in=expires_in
    )


def loads(
    s,
    key=None,
    salt="plain.loginlink",
    serializer=JSONSerializer,
    fallback_keys=None,
):
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
