from __future__ import annotations

from http import cookies

from plain.runtime import settings
from plain.signing import BadSignature, TimestampSigner
from plain.utils.encoding import force_bytes


def parse_cookie(cookie: str) -> dict[str, str]:
    """
    Return a dictionary parsed from a `Cookie:` header string.
    """
    cookiedict = {}
    for chunk in cookie.split(";"):
        if "=" in chunk:
            key, val = chunk.split("=", 1)
        else:
            # Assume an empty name per
            # https://bugzilla.mozilla.org/show_bug.cgi?id=169091
            key, val = "", chunk
        key, val = key.strip(), val.strip()
        if key or val:
            # unquote using Python's algorithm.
            cookiedict[key] = cookies._unquote(val)
    return cookiedict


def _cookie_key(key: str) -> bytes:
    """
    Generate a key for cookie signing that matches the pattern used by
    set_signed_cookie and get_signed_cookie.
    """
    return b"plain.http.cookies" + force_bytes(key)


def get_signed_cookie_signer(key: str, salt: str = "") -> TimestampSigner:
    """
    Create a TimestampSigner for signed cookies with the same configuration
    used by both set_signed_cookie and get_signed_cookie.
    """
    return TimestampSigner(
        key=_cookie_key(settings.SECRET_KEY).decode(),
        fallback_keys=[_cookie_key(k).decode() for k in settings.SECRET_KEY_FALLBACKS],
        salt=key + salt,
    )


def sign_cookie_value(key: str, value: str, salt: str = "") -> str:
    """
    Sign a cookie value using the standard Plain cookie signing approach.
    """
    signer = get_signed_cookie_signer(key, salt)
    return signer.sign(value)


def unsign_cookie_value(
    key: str,
    signed_value: str,
    salt: str = "",
    max_age: int | None = None,
    default: str | None = None,
) -> str | None:
    """
    Unsign a cookie value using the standard Plain cookie signing approach.
    Returns the default value if the signature is invalid or the cookie has expired.
    """
    signer = get_signed_cookie_signer(key, salt)
    try:
        return signer.unsign(signed_value, max_age=max_age)
    except BadSignature:
        return default
