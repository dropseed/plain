import os
from html.parser import HTMLParser

import mistune
from pygments import highlight
from pygments.formatters import html
from pygments.lexers import get_lexer_by_name

from plain.urls import reverse
from plain.utils.text import slugify


class PagesRenderer(mistune.HTMLRenderer):
    def __init__(self, current_page_path, pages_registry, **kwargs):
        super().__init__(**kwargs)
        self.current_page_path = current_page_path
        self.pages_registry = pages_registry

    def link(self, text, url, title=None):
        """Convert relative markdown links to proper page URLs."""
        # Check if it's a relative link (starts with ./ or ../, or is just a filename)
        is_relative = url.startswith(("./", "../")) or (
            not url.startswith(("http://", "https://", "/", "#")) and ":" not in url
        )

        if is_relative:
            # Resolve relative to current page's directory
            current_dir = os.path.dirname(self.current_page_path)
            resolved_path = os.path.normpath(os.path.join(current_dir, url))
            page = self.pages_registry.get_page_from_path(resolved_path)

            # Get the primary URL name for link conversion
            url_name = page.get_url_name()
            if url_name:
                url = reverse(f"pages:{url_name}")

        return super().link(text, url, title)

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


def render_markdown(content, current_page_path):
    from .registry import pages_registry

    renderer = PagesRenderer(
        current_page_path=current_page_path, pages_registry=pages_registry, escape=False
    )
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
