"""HTML-aware tokenizer.

Phase 0 scope: emit a flat token stream from a template body string. Tokens
carry enough structure for the parser to build a tag tree. Attribute values
are split into literal segments and `{expr}` segments so the compiler/renderer
can apply contextual escape.

Out of scope for Phase 0:
- `<script>` / `<style>` opaque body handling (treated as regular text)
- Source positions (line/col) — included as offsets but not yet plumbed into
  every error path
- Unicode tag-name validation (we accept ASCII letter prefixes)
"""

from __future__ import annotations

from dataclasses import dataclass, field

VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class TokenizeError(Exception):
    pass


@dataclass
class TextToken:
    text: str
    offset: int


@dataclass
class ExprToken:
    code: str
    offset: int


@dataclass
class HtmlCommentToken:
    text: str
    offset: int


@dataclass
class DoctypeToken:
    text: str
    offset: int


@dataclass
class StartTagToken:
    name: str
    attrs: list[tuple[str, list | None, bool]] = field(default_factory=list)
    self_closing: bool = False
    offset: int = 0


@dataclass
class EndTagToken:
    name: str
    offset: int = 0


Token = (
    TextToken
    | ExprToken
    | HtmlCommentToken
    | DoctypeToken
    | StartTagToken
    | EndTagToken
)


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)
    text_buf: list[str] = []
    text_start = 0

    def flush_text() -> None:
        if text_buf:
            tokens.append(TextToken("".join(text_buf), text_start))
            text_buf.clear()

    while i < n:
        c = source[i]

        # HTML comment
        if source.startswith("<!--", i):
            flush_text()
            end = source.find("-->", i + 4)
            if end == -1:
                raise TokenizeError(f"Unterminated HTML comment at offset {i}")
            tokens.append(HtmlCommentToken(source[i + 4 : end], i))
            i = end + 3
            text_start = i
            continue

        # Doctype
        if source.startswith("<!", i):
            flush_text()
            end = source.find(">", i + 2)
            if end == -1:
                raise TokenizeError(f"Unterminated doctype at offset {i}")
            tokens.append(DoctypeToken(source[i : end + 1], i))
            i = end + 1
            text_start = i
            continue

        # End tag
        if source.startswith("</", i):
            flush_text()
            end = source.find(">", i + 2)
            if end == -1:
                raise TokenizeError(f"Unterminated end tag at offset {i}")
            name = source[i + 2 : end].strip().lower()
            if not name:
                raise TokenizeError(f"Empty end tag at offset {i}")
            tokens.append(EndTagToken(name, i))
            i = end + 1
            text_start = i
            continue

        # Start tag
        if c == "<" and i + 1 < n and (source[i + 1].isalpha() or source[i + 1] == "/"):
            flush_text()
            tok, new_i = _consume_start_tag(source, i)
            tokens.append(tok)
            i = new_i
            text_start = i
            continue

        # Template comment {# ... #}
        if source.startswith("{#", i):
            flush_text()
            end = source.find("#}", i + 2)
            if end == -1:
                raise TokenizeError(f"Unterminated template comment at offset {i}")
            i = end + 2
            text_start = i
            continue

        # Literal { and } via {{ and }}
        if source.startswith("{{", i):
            text_buf.append("{")
            i += 2
            continue
        if source.startswith("}}", i):
            text_buf.append("}")
            i += 2
            continue

        # Expression {expr}
        if c == "{":
            flush_text()
            expr, new_i = _consume_expr(source, i)
            tokens.append(ExprToken(expr, i))
            i = new_i
            text_start = i
            continue

        text_buf.append(c)
        i += 1

    flush_text()
    return tokens


def _consume_expr(source: str, start: int) -> tuple[str, int]:
    """Consume a {python_expr} starting at the '{' position.

    Tracks brace depth so nested dict/set literals work: ``{ {"a": 1} }``.
    Honors string quoting to avoid being fooled by braces inside strings.
    """
    assert source[start] == "{"
    i = start + 1
    n = len(source)
    depth = 1
    quote: str | None = None
    expr_start = i
    while i < n:
        c = source[i]
        if quote is not None:
            if c == "\\" and i + 1 < n:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ('"', "'"):
            quote = c
            i += 1
            continue
        if c == "{":
            depth += 1
            i += 1
            continue
        if c == "}":
            depth -= 1
            if depth == 0:
                return source[expr_start:i], i + 1
            i += 1
            continue
        i += 1
    raise TokenizeError(f"Unterminated expression starting at offset {start}")


def _consume_start_tag(source: str, start: int) -> tuple[StartTagToken, int]:
    """Consume `<tag attr1 attr2="..." attr3={expr}>` or `<tag/>`."""
    assert source[start] == "<"
    i = start + 1
    n = len(source)
    # Tag name
    name_start = i
    while i < n and (source[i].isalnum() or source[i] in "-_:"):
        i += 1
    name = source[name_start:i].lower()
    if not name:
        raise TokenizeError(f"Expected tag name at offset {start}")

    attrs: list[tuple[str, list | None, bool]] = []
    self_closing = False

    while i < n:
        # Skip whitespace
        while i < n and source[i] in " \t\r\n":
            i += 1
        if i >= n:
            raise TokenizeError(f"Unterminated start tag at offset {start}")

        c = source[i]
        if c == ">":
            i += 1
            break
        if c == "/" and i + 1 < n and source[i + 1] == ">":
            self_closing = True
            i += 2
            break

        # Attribute name
        attr_name_start = i
        while i < n and source[i] not in " \t\r\n=/>":
            i += 1
        attr_name = source[attr_name_start:i]
        if not attr_name:
            raise TokenizeError(f"Expected attribute name at offset {attr_name_start}")

        # Optional value
        # Skip whitespace before '='
        j = i
        while j < n and source[j] in " \t\r\n":
            j += 1
        if j < n and source[j] == "=":
            i = j + 1
            # Skip whitespace after '='
            while i < n and source[i] in " \t\r\n":
                i += 1
            if i >= n:
                raise TokenizeError(f"Expected attribute value at offset {i}")

            ac = source[i]
            if ac == '"' or ac == "'":
                segments, i = _consume_quoted_attr(source, i, ac)
                # If the entire value is one expression and no literal, mark as expression
                is_expr = (
                    len(segments) == 1
                    and isinstance(segments[0], tuple)
                    and segments[0][0] == "expr"
                )
                attrs.append((attr_name, segments, is_expr))
            elif ac == "{":
                expr, i = _consume_expr(source, i)
                attrs.append((attr_name, [("expr", expr)], True))
            else:
                # Unquoted value: read until whitespace or '>' or '/>'
                val_start = i
                while (
                    i < n
                    and source[i] not in " \t\r\n>"
                    and not source.startswith("/>", i)
                ):
                    i += 1
                attrs.append((attr_name, [("text", source[val_start:i])], False))
        else:
            # Boolean attribute (no value)
            attrs.append((attr_name, None, False))

    return (
        StartTagToken(name=name, attrs=attrs, self_closing=self_closing, offset=start),
        i,
    )


def _consume_quoted_attr(source: str, start: int, quote: str) -> tuple[list, int]:
    """Consume `"static {expr} more"` returning a list of ('text', s) and ('expr', code) segments."""
    assert source[start] == quote
    i = start + 1
    n = len(source)
    segments: list = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            segments.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        c = source[i]
        if c == quote:
            flush()
            return segments, i + 1
        if source.startswith("{{", i):
            buf.append("{")
            i += 2
            continue
        if source.startswith("}}", i):
            buf.append("}")
            i += 2
            continue
        if c == "{":
            flush()
            expr, i = _consume_expr(source, i)
            segments.append(("expr", expr))
            continue
        buf.append(c)
        i += 1
    raise TokenizeError(f"Unterminated quoted attribute at offset {start}")
