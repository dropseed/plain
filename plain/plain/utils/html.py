"""HTML utilities suitable for global use."""

from __future__ import annotations

import html
import json
from html.parser import HTMLParser
from typing import Any

from plain.internal import internalcode
from plain.utils.functional import Promise, keep_lazy, keep_lazy_text
from plain.utils.safestring import SafeString, mark_safe


@keep_lazy(SafeString)
def escape(text: Any) -> SafeString:
    """
    Return the given text with ampersands, quotes and angle brackets encoded
    for use in HTML.

    Always escape input, even if it's already escaped and marked as such.
    This may result in double-escaping. If this is a concern, use
    conditional_escape() instead.
    """
    return SafeString(html.escape(str(text)))


_json_script_escapes = {
    ord(">"): "\\u003E",
    ord("<"): "\\u003C",
    ord("&"): "\\u0026",
}


def json_script(
    value: Any,
    element_id: str | None = None,
    nonce: str = "",
    encoder: type[json.JSONEncoder] | None = None,
) -> SafeString:
    """
    Escape all the HTML/XML special characters with their unicode escapes, so
    value is safe to be output anywhere except for inside a tag attribute. Wrap
    the escaped JSON in a script tag.

    Args:
        value: The data to encode as JSON
        element_id: Optional ID attribute for the script tag
        nonce: Optional CSP nonce for inline script tags
        encoder: Optional custom JSON encoder class
    """
    from plain.json import PlainJSONEncoder

    json_str = json.dumps(value, cls=encoder or PlainJSONEncoder).translate(
        _json_script_escapes
    )
    id_attr = f' id="{element_id}"' if element_id else ""
    nonce_attr = f' nonce="{nonce}"' if nonce else ""
    return mark_safe(
        f'<script{id_attr}{nonce_attr} type="application/json">{json_str}</script>'
    )


def conditional_escape(text: Any) -> SafeString | str:
    """
    Similar to escape(), except that it doesn't operate on pre-escaped strings.

    This function relies on the __html__ convention used both by Plain's
    SafeData class and by third-party libraries like markupsafe.
    """
    if isinstance(text, Promise):
        text = str(text)
    if hasattr(text, "__html__"):
        return text.__html__()  # type: ignore[union-attr]
    else:
        return escape(text)


def format_html(format_string: str, *args: Any, **kwargs: Any) -> SafeString:
    """
    Similar to str.format, but pass all arguments through conditional_escape(),
    and call mark_safe() on the result. This function should be used instead
    of str.format or % interpolation to build up small HTML fragments.
    """
    args_safe = map(conditional_escape, args)
    kwargs_safe = {k: conditional_escape(v) for (k, v) in kwargs.items()}
    return mark_safe(format_string.format(*args_safe, **kwargs_safe))


@internalcode
class MLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.reset()
        self.fed: list[str] = []

    def handle_data(self, data: str) -> None:
        self.fed.append(data)

    def handle_entityref(self, name: str) -> None:
        self.fed.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.fed.append(f"&#{name};")

    def get_data(self) -> str:
        return "".join(self.fed)


def _strip_once(value: str) -> str:
    """
    Internal tag stripping utility used by strip_tags.
    """
    s = MLStripper()
    s.feed(value)
    s.close()
    return s.get_data()


@keep_lazy_text
def strip_tags(value: Any) -> str:
    """Return the given HTML with all tags stripped."""
    # Note: in typical case this loop executes _strip_once once. Loop condition
    # is redundant, but helps to reduce number of executions of _strip_once.
    value = str(value)
    while "<" in value and ">" in value:
        new_value = _strip_once(value)
        if value.count("<") == new_value.count("<"):
            # _strip_once wasn't able to detect more tags.
            break
        value = new_value
    return value


def avoid_wrapping(value: str) -> str:
    """
    Avoid text wrapping in the middle of a phrase by adding non-breaking
    spaces where there previously were normal spaces.
    """
    return value.replace(" ", "\xa0")
