from __future__ import annotations

from plain.html.typecheck.declarations import parse as parse_declarations
from plain.html.typecheck.synth import synthesize


def _decls(**fm):
    return parse_declarations(fm)


def test_attrs_become_keyword_only_params():
    decls = _decls(attrs={"name": "str", "count": "int = 0"})
    synth = synthesize("<p>hi</p>", decls)
    assert "def _plain_html_check(" in synth.source
    assert "*," in synth.source
    assert "name: str," in synth.source
    assert "count: int = 0," in synth.source


def test_imports_block_propagates():
    decls = _decls(imports=["from datetime import datetime"])
    synth = synthesize("<p>{datetime.now()}</p>", decls)
    assert "from datetime import datetime" in synth.source


def test_dotted_attr_type_produces_module_import():
    decls = _decls(attrs={"user": "app.users.User"})
    synth = synthesize("<p>{user.name}</p>", decls)
    assert "import app.users" in synth.source


def test_expr_token_lands_on_synth_line():
    decls = _decls(attrs={"name": "str"})
    body = "<p>{name}</p>"
    synth = synthesize(body, decls)
    # Exactly one tracked expression; check it round-trips.
    [(line, entry)] = synth.line_map.items()
    assert entry.kind == "expr"
    # `{` is at body offset 3.
    assert entry.template_offset == 3
    synth_lines = synth.source.splitlines()
    # Synth lines are 1-indexed; assert the recorded line actually contains
    # the expression we tracked.
    assert "(name)" in synth_lines[line - 1]


def test_for_directive_opens_scope_for_body_expressions():
    decls = _decls(attrs={"items": "list[int]"})
    body = "<ul><li :for={i in items}>{i}</li></ul>"
    synth = synthesize(body, decls)
    src = synth.source
    assert "for i in (items):" in src
    # The inner `{i}` should be inside the for-block, so it appears
    # *after* the for-loop header in the source.
    for_idx = src.index("for i in (items):")
    inner_idx = src.index("_ = (i)")
    assert inner_idx > for_idx


def test_if_directive_emits_truthiness_check():
    """`:if` opens a real `if`-block so ty narrows the condition's type
    within the element body. `<template :if={x}>{x.field}</template>` no
    longer requires a second guard."""
    decls = _decls(attrs={"show": "bool"})
    body = "<span :if={show}>hi</span>"
    synth = synthesize(body, decls)
    assert "if (show):" in synth.source


def test_slot_params_include_default_and_children():
    decls = _decls(slots={"header": "optional"})
    synth = synthesize("<p>{header}</p>", decls)
    assert 'header: SafeString = SafeString("")' in synth.source
    assert 'children: SafeString = SafeString("")' in synth.source
    assert 'default: SafeString = SafeString("")' in synth.source


def test_synth_source_is_valid_python():
    """Synth output must parse — invariant the backend depends on."""
    import ast

    decls = _decls(
        attrs={
            "name": "str",
            "count": "int = 0",
            "items": "list[int] = []",
        },
        imports=["from datetime import datetime"],
        slots={"header": "optional"},
    )
    body = """
<div :if={count > 0}>
  <p :for={i in items}>{i}: {name}</p>
  <span>{datetime.now()}</span>
  {header}
</div>
"""
    synth = synthesize(body, decls)
    ast.parse(synth.source)  # must not raise
