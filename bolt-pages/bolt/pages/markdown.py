import mistune
from pygments import highlight
from pygments.formatters import html
from pygments.lexers import get_lexer_by_name


class HighlightRenderer(mistune.HTMLRenderer):
    def block_code(self, code, info=None):
        if info:
            lexer = get_lexer_by_name(info, stripall=True)
            formatter = html.HtmlFormatter()
            return highlight(code, lexer, formatter)
        return "<pre><code>" + mistune.escape(code) + "</code></pre>"


def render_markdown(content):
    renderer = HighlightRenderer(escape=False)
    markdown = mistune.create_markdown(
        renderer=renderer, plugins=["strikethrough", "table"]
    )
    return markdown(content)
