"""Lazy regex compilation helper used outside of URL routing."""

from __future__ import annotations

import re

from plain.utils.functional import SimpleLazyObject


def _lazy_re_compile(
    regex: str | bytes | re.Pattern[str] | re.Pattern[bytes], flags: int = 0
) -> SimpleLazyObject:
    """Lazily compile a regex with flags."""

    def _compile() -> re.Pattern[str] | re.Pattern[bytes]:
        if isinstance(regex, str | bytes):
            return re.compile(regex, flags)
        else:
            assert not flags, "flags must be empty if regex is passed pre-compiled"
            return regex

    return SimpleLazyObject(_compile)
