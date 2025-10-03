from __future__ import annotations

import base64
import unicodedata
from binascii import Error as BinasciiError

from plain.internal import internalcode


@internalcode
def urlsafe_base64_encode(s: bytes) -> str:
    """
    Encode a bytestring to a base64 string for use in URLs. Strip any trailing
    equal signs.
    """
    return base64.urlsafe_b64encode(s).rstrip(b"\n=").decode("ascii")


@internalcode
def urlsafe_base64_decode(s: str) -> bytes:
    """
    Decode a base64 encoded string. Add back any trailing equal signs that
    might have been stripped.
    """
    s_bytes = s.encode()
    try:
        return base64.urlsafe_b64decode(
            s_bytes.ljust(len(s_bytes) + len(s_bytes) % 4, b"=")
        )
    except (LookupError, BinasciiError) as e:
        raise ValueError(e)


@internalcode
def unicode_ci_compare(s1: str, s2: str) -> bool:
    """
    Perform case-insensitive comparison of two identifiers, using the
    recommended algorithm from Unicode Technical Report 36, section
    2.11.2(B)(2).
    """
    return (
        unicodedata.normalize("NFKC", s1).casefold()
        == unicodedata.normalize("NFKC", s2).casefold()
    )
