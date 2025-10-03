from __future__ import annotations

import os
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

import mistune
from pygments import highlight
from pygments.formatters import html
from pygments.lexers import get_lexer_by_name

from plain.urls import reverse
from plain.utils.text import slugify

if TYPE_CHECKING:
    from .registry import PagesRegistry


class PagesRenderer(mistune.HTMLRenderer):
    def __init__(
        self, current_page_path: str, pages_registry: PagesRegistry, **kwargs: Any
    ):
        super().__init__(**kwargs)
        self.current_page_path = current_page_path
        self.pages_registry = pages_registry

    def link(self, text: str, url: str, title: str | None = None) -> str:
        """Convert relative markdown links to proper page URLs."""
        # Check if it's a relative link (starts with ./ or ../, or is just a filename)
        is_relative = url.startswith(("./", "../")) or (
            not url.startswith(("http://", "https://", "/", "#")) and ":" not in url
        )

        if is_relative:
            # Parse URL to extract components
            parsed_url = urlparse(url)

            # Resolve relative to current page's directory using just the path component
            current_dir = os.path.dirname(self.current_page_path)
            resolved_path = os.path.normpath(os.path.join(current_dir, parsed_url.path))
            page = self.pages_registry.get_page_from_path(resolved_path)

            # Get the primary URL name for link conversion
            url_name = page.get_url_name()
            if url_name:
                base_url = reverse(f"pages:{url_name}")
                # Reconstruct URL with preserved query params and fragment
                url = str(
                    urlunparse(
                        (
                            parsed_url.scheme,  # scheme (empty for relative)
                            parsed_url.netloc,  # netloc (empty for relative)
                            base_url,  # path (our converted URL)
                            parsed_url.params,  # params
                            parsed_url.query,  # query
                            parsed_url.fragment,  # fragment
                        )
                    )
                )

        return super().link(text, url, title)

    def heading(self, text: str, level: int, **attrs: Any) -> str:
        """Automatically add an ID to headings if one is not provided."""

        if "id" not in attrs:
            inner_text = get_inner_text(text)
            inner_text = inner_text.replace(
                ".", "-"
            )  # Replace dots with hyphens (slugify won't)
            attrs["id"] = slugify(inner_text)

        return super().heading(text, level, **attrs)

    def block_code(self, code: str, info: str | None = None) -> str:
        """Highlight code blocks using Pygments."""

        if info:
            lexer = get_lexer_by_name(info, stripall=True)
            formatter = html.HtmlFormatter(wrapcode=True)
            return highlight(code, lexer, formatter)

        return "<pre><code>" + mistune.escape(code) + "</code></pre>"


def render_markdown(content: str, current_page_path: str) -> str:
    from .registry import pages_registry

    renderer = PagesRenderer(
        current_page_path=current_page_path, pages_registry=pages_registry, escape=False
    )
    markdown = mistune.create_markdown(
        renderer=renderer, plugins=["strikethrough", "table"]
    )
    return markdown(content)  # type: ignore[return-value]


class InnerTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_content: list[str] = []

    def handle_data(self, data: str) -> None:
        # Collect all text data
        self.text_content.append(data.strip())


def get_inner_text(html_content: str) -> str:
    parser = InnerTextParser()
    parser.feed(html_content)
    return " ".join([text for text in parser.text_content if text])
