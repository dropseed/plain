from plain.html.parser import ElementNode, TemplateCommentNode, parse
from plain.html.tokenizer import TemplateCommentToken, tokenize


def test_template_comment_preserved_in_tree():
    # Renderer discards `{# … #}`, but tokenizer/parser must emit a node so
    # the future formatter can round-trip comments.
    tokens = tokenize("<p>{# keep me #}hi</p>")
    assert any(
        isinstance(t, TemplateCommentToken) and t.text == " keep me " for t in tokens
    )
    tree = parse(tokens)
    p = tree[0]
    assert isinstance(p, ElementNode)
    assert any(
        isinstance(c, TemplateCommentNode) and c.text == " keep me " for c in p.children
    )
