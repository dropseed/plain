from html.parser import HTMLParser

import mistune
from pygments import highlight
from pygments.formatters import html
from pygments.lexers import get_lexer_by_name

from plain.utils.text import slugify


class PagesRenderer(mistune.HTMLRenderer):
    def heading(self, text, level, **attrs):
        """Automatically add an ID to headings if one is not provided."""

        if "id" not in attrs:
            inner_text = get_inner_text(text)
            inner_text = inner_text.replace(
                ".", "-"
            )  # Replace dots with hyphens (slugify won't)
            attrs["id"] = slugify(inner_text)

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


class InnerTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_content = []

    def handle_data(self, data):
        # Collect all text data
        self.text_content.append(data.strip())


def get_inner_text(html_content):
    parser = InnerTextParser()
    parser.feed(html_content)
    return " ".join([text for text in parser.text_content if text])
