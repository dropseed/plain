from plain.html.whitespace import (
    INLINE_ELEMENTS,
    VERBATIM_ELEMENTS,
    is_block,
    is_inline,
    is_verbatim,
)


def test_classifications_are_disjoint():
    assert INLINE_ELEMENTS.isdisjoint(VERBATIM_ELEMENTS)


def test_verbatim_recognizes_pre_textarea_script_style():
    for tag in ("pre", "textarea", "script", "style"):
        assert is_verbatim(tag)
        assert not is_inline(tag)
        assert not is_block(tag)


def test_inline_recognizes_phrasing_content():
    # Spot check the canonical phrasing elements.
    for tag in ("a", "span", "strong", "em", "code", "img", "br"):
        assert is_inline(tag)
        assert not is_verbatim(tag)
        assert not is_block(tag)


def test_block_recognizes_flow_content():
    # Anything not inline and not verbatim defaults to block — this is
    # how unknown tags (custom elements, framework tags) get treated.
    for tag in ("div", "section", "article", "p", "main", "form", "x-custom"):
        assert is_block(tag)
        assert not is_inline(tag)
        assert not is_verbatim(tag)


def test_button_and_label_are_inline():
    # These are sometimes mistaken for block. WHATWG classifies them as
    # phrasing content; layout-wise they participate inline by default.
    assert is_inline("button")
    assert is_inline("label")


def test_template_is_inline():
    # plain.html uses `<template>` as an engine-aware fragment/include
    # construct. WHATWG defines `<template>` as phrasing content; treating
    # it as inline keeps formatter behavior consistent across vanilla HTML
    # and engine-aware uses.
    assert is_inline("template")
