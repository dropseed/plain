from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

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
        "source",
        "track",
        "wbr",
    }
)

# HTML5 makes the closing tag for these elements optional, so we implicitly
# close them on a parent's end tag and don't flag them if left on the stack.
OPTIONALLY_CLOSED = frozenset(
    {
        "html",
        "head",
        "body",
        "p",
        "li",
        "dt",
        "dd",
        "tr",
        "td",
        "th",
        "thead",
        "tbody",
        "tfoot",
        "option",
        "optgroup",
        "colgroup",
        "rt",
        "rp",
    }
)

# If the key tag is on top of the stack and any value tag opens next, the
# key tag is implicitly closed (HTML5 parsing rule). Without this, valid
# markup like <li>a<li>b</ul> would produce false "unclosed <li>" errors.
AUTO_CLOSE_BEFORE: dict[str, frozenset[str]] = {
    "li": frozenset({"li"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "p": frozenset(
        {
            "address",
            "article",
            "aside",
            "blockquote",
            "details",
            "div",
            "dl",
            "fieldset",
            "figcaption",
            "figure",
            "footer",
            "form",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hr",
            "main",
            "nav",
            "ol",
            "p",
            "pre",
            "section",
            "table",
            "ul",
        }
    ),
    "tr": frozenset({"tr"}),
    "td": frozenset({"td", "th", "tr"}),
    "th": frozenset({"td", "th", "tr"}),
    "thead": frozenset({"tbody", "tfoot"}),
    "tbody": frozenset({"tbody", "tfoot"}),
    "option": frozenset({"option", "optgroup"}),
    "optgroup": frozenset({"optgroup"}),
}


@dataclass(frozen=True)
class HTMLError:
    line: int
    col: int
    message: str

    def format(self) -> str:
        return f"line {self.line}, col {self.col}: {self.message}"


class _Validator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[HTMLError] = []
        # (tag, line, col)
        self.stack: list[tuple[str, int, int]] = []
        # id -> (line, col) of first occurrence
        self.ids: dict[str, tuple[int, int]] = {}
        # Pending label[for] checks resolved at end of parse
        self.label_targets: list[tuple[str, int, int]] = []

    def _record_id_and_label(
        self, tag: str, attrs_dict: dict[str, str | None], line: int, col: int
    ) -> None:
        id_val = attrs_dict.get("id")
        if id_val:
            if id_val in self.ids:
                first_line, _ = self.ids[id_val]
                self.errors.append(
                    HTMLError(
                        line,
                        col,
                        f"Duplicate id={id_val!r} (first at line {first_line})",
                    )
                )
            else:
                self.ids[id_val] = (line, col)

        if tag == "label":
            for_val = attrs_dict.get("for")
            if for_val:
                self.label_targets.append((for_val, line, col))

    def _auto_close(self, new_tag: str) -> None:
        # Pop any tags that should be implicitly closed when new_tag opens.
        while self.stack:
            top_tag = self.stack[-1][0]
            closers = AUTO_CLOSE_BEFORE.get(top_tag)
            if closers and new_tag in closers:
                self.stack.pop()
            else:
                break

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line, col = self.getpos()
        attrs_dict = dict(attrs)

        self._record_id_and_label(tag, attrs_dict, line, col)

        if tag == "a":
            for ancestor_tag, _, _ in self.stack:
                if ancestor_tag == "a":
                    self.errors.append(
                        HTMLError(line, col, "Nested <a> inside another <a>")
                    )
                    break

        if tag == "button":
            for ancestor_tag, _, _ in self.stack:
                if ancestor_tag in ("a", "button"):
                    self.errors.append(
                        HTMLError(
                            line,
                            col,
                            f"<button> inside <{ancestor_tag}> (interactive nesting)",
                        )
                    )
                    break

        if tag in VOID_ELEMENTS:
            return

        self._auto_close(tag)
        self.stack.append((tag, line, col))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # XML-style self-closing like <br/> or <div/>. For our purposes treat
        # it as a start tag that does not push (HTML5 ignores the slash on
        # non-void elements but agents commonly write <input/>).
        line, col = self.getpos()
        attrs_dict = dict(attrs)
        self._record_id_and_label(tag, attrs_dict, line, col)

    def handle_endtag(self, tag: str) -> None:
        line, col = self.getpos()

        if tag in VOID_ELEMENTS:
            self.errors.append(
                HTMLError(line, col, f"</{tag}> closing tag for void element")
            )
            return

        # Pop any optionally-closed tags off the top before matching. This
        # handles cases like <ul><li>a<li>b</ul> where the <li>s never get an
        # explicit closing tag.
        while (
            self.stack
            and self.stack[-1][0] != tag
            and self.stack[-1][0] in OPTIONALLY_CLOSED
        ):
            self.stack.pop()

        if not self.stack:
            self.errors.append(
                HTMLError(line, col, f"Unexpected </{tag}> with no open tag")
            )
            return

        if self.stack[-1][0] == tag:
            self.stack.pop()
            return

        # Mismatched: search for a matching open tag deeper in the stack.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for u_tag, u_line, u_col in self.stack[i + 1 :]:
                    self.errors.append(HTMLError(u_line, u_col, f"Unclosed <{u_tag}>"))
                self.stack = self.stack[:i]
                return

        self.errors.append(
            HTMLError(line, col, f"Unexpected </{tag}> (no matching open tag)")
        )

    def finish(self) -> None:
        for tag, line, col in self.stack:
            if tag in OPTIONALLY_CLOSED:
                continue
            self.errors.append(HTMLError(line, col, f"Unclosed <{tag}>"))

        for target, line, col in self.label_targets:
            if target not in self.ids:
                self.errors.append(
                    HTMLError(
                        line,
                        col,
                        f"<label for={target!r}> has no matching id in document",
                    )
                )


def validate_html(html: str) -> list[HTMLError]:
    """Return a list of "broken" HTML issues found in `html`.

    Focuses on unambiguous bugs (parse errors, mismatched/unclosed tags,
    duplicate ids, orphan label[for], nested interactive elements). Stylistic
    or "should" issues (missing alt, ARIA suggestions, etc.) are intentionally
    not reported.
    """
    validator = _Validator()
    validator.feed(html)
    validator.close()
    validator.finish()
    return validator.errors
