import mistune
from pygments import highlight
from pygments.formatters import html
from pygments.lexers import get_lexer_by_name

from plain.utils.text import slugify


class PagesRenderer(mistune.HTMLRenderer):
    def heading(self, text, level, **attrs):
        """Automatically add an ID to headings if one is not provided."""

        if "id" not in attrs:
            attrs["id"] = slugify(text)

        return super().heading(text, level, **attrs)

    def block_code(self, code, info=None):
        """Highlight code blocks using Pygments."""

        if info:
            lexer = get_lexer_by_name(info, stripall=True)
            formatter = html.HtmlFormatter(wrapcode=True)
            return highlight(code, lexer, formatter)

        return "<pre><code>" + mistune.escape(code) + "</code></pre>"


def render_markdown(content):
    renderer = PagesRenderer(escape=False)
    markdown = mistune.create_markdown(
        renderer=renderer, plugins=["strikethrough", "table"]
    )
    return markdown(content)
