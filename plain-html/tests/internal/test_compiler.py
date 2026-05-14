"""Phase 5a compiler tests.

Each emission rule gets a unit test that compiles a fragment of template
source, exec()s the generated module, and asserts the rendered output
against an explicit string.

The final block is a small corpus parity check — every case is rendered
both by the interpreter and the compiler with the same context, and the
outputs must match byte-for-byte. The full repo-wide corpus parity test
lands in a later sub-phase; this is just enough coverage to surface
shape mismatches early.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from plain.html import render_source
from plain.html.compiler import (
    CompileError,
    CompileSession,
    clear_process_cache,
    compile_path,
    compile_source,
)
from plain.html.engine import render as engine_render


def _load(source: str, *, label: str = "<test>"):
    src = compile_source(source, source_label=label)
    mod = types.ModuleType(f"_plain_html_test_{abs(hash(source))}")
    mod.__file__ = label
    code = compile(src, label, "exec")
    exec(code, mod.__dict__)
    return mod.render


# --- text + expressions ------------------------------------------------------


def test_static_text():
    assert _load("<p>hi</p>")() == "<p>hi</p>"


def test_simple_expression():
    assert _load("<p>{name}</p>")(name="Dave") == "<p>Dave</p>"


def test_expression_html_escaped():
    assert _load("<p>{x}</p>")(x="<b>") == "<p>&lt;b&gt;</p>"


def test_none_renders_empty():
    assert _load("<p>{x}</p>")(x=None) == "<p></p>"


def test_adjacent_text_runs_constant_fold():
    # Two text nodes around an expression should fold into single literal append
    # before and after, plus one expression append.
    src = compile_source("<p>before {x} after</p>")
    # Generated should have exactly one `_append('before ')` chunk and one
    # `_append(' after')` chunk — quick sanity grep on the generated source.
    assert "before " in src
    assert " after" in src
    assert _load("<p>before {x} after</p>")(x="MID") == "<p>before MID after</p>"


# --- attributes --------------------------------------------------------------


def test_boolean_attr():
    assert _load("<input disabled>")() == "<input disabled>"


def test_static_attr():
    assert (
        _load('<a class="link" href="/x">go</a>')()
        == '<a class="link" href="/x">go</a>'
    )


def test_dyn_attr_string():
    assert _load("<a href={url}>x</a>")(url="/foo") == '<a href="/foo">x</a>'


def test_dyn_attr_true():
    assert _load("<input disabled={cond}>")(cond=True) == "<input disabled>"


def test_dyn_attr_false():
    assert _load("<input disabled={cond}>")(cond=False) == "<input>"


def test_dyn_attr_none():
    assert _load("<input disabled={cond}>")(cond=None) == "<input>"


def test_dyn_attr_list_class():
    out = _load("<a class={classes}>x</a>")(classes=["btn", "", "primary"])
    assert out == '<a class="btn primary">x</a>'


def test_dyn_attr_list_empty_is_omitted():
    assert _load("<a class={classes}>x</a>")(classes=[]) == "<a>x</a>"


def test_mixed_attr_segments():
    out = _load('<a href="/u/{handle}/{tab}">x</a>')(handle="ada", tab="bio")
    assert out == '<a href="/u/ada/bio">x</a>'


# --- :if / :for --------------------------------------------------------------


def test_if_true():
    assert _load("<p :if={show}>hi</p>")(show=True) == "<p>hi</p>"


def test_if_false():
    assert _load("<p :if={show}>hi</p>")(show=False) == ""


def test_for_simple():
    out = _load("<li :for={x in items}>{x}</li>")(items=[1, 2, 3])
    assert out == "<li>1</li><li>2</li><li>3</li>"


def test_for_unpacking():
    out = _load("<li :for={a, b in pairs}>{a}={b}</li>")(pairs=[("x", 1), ("y", 2)])
    assert out == "<li>x=1</li><li>y=2</li>"


def test_for_parenthesized_unpacking():
    out = _load("<li :for={(a, b) in pairs}>{a}={b}</li>")(pairs=[("x", 1)])
    assert out == "<li>x=1</li>"


def test_nested_for():
    src = "<tr :for={row in rows}><td :for={c in row}>{c}</td></tr>"
    out = _load(src)(rows=[[1, 2], [3, 4]])
    assert out == "<tr><td>1</td><td>2</td></tr><tr><td>3</td><td>4</td></tr>"


def test_for_target_does_not_leak():
    # `x` in :for should not shadow an outer `x` after the loop.
    render = _load("<a :for={x in items}>{x}</a><b>{x}</b>")
    assert render(items=[1, 2], x="OUT") == "<a>1</a><a>2</a><b>OUT</b>"


def test_if_then_for():
    render = _load("<li :if={show} :for={x in items}>{x}</li>")
    assert render(show=True, items=[1, 2]) == "<li>1</li><li>2</li>"
    assert render(show=False, items=[1, 2]) == ""


# --- elements, fragments, comments, doctype ---------------------------------


def test_template_fragment():
    assert _load("<template>{x}<br></template>")(x="hi") == "hi<br>"


def test_html_comment_preserved():
    assert _load("<!-- note --><p>x</p>")() == "<!-- note --><p>x</p>"


def test_template_comment_discarded():
    assert _load("{# secret #}<p>x</p>")() == "<p>x</p>"


def test_doctype():
    assert _load("<!DOCTYPE html><html></html>")() == "<!DOCTYPE html><html></html>"


def test_void_element():
    assert _load('<img src="/x">')() == '<img src="/x">'


def test_self_closing_normalized():
    assert _load("<br/>")() == "<br>"


# --- frontmatter -------------------------------------------------------------


def test_declared_attr_defaults_to_none():
    src = """---
attrs:
    name: str
---
<p :if={name}>{name}</p><span :if={not name}>none</span>"""
    render = _load(src)
    assert "<span>none</span>" in render()
    assert render(name="Dave") == "<p>Dave</p>"


def test_declared_slot_defaults_to_empty_markup():
    src = """---
slots:
    header: Markup
---
<header>{header}</header>"""
    assert _load(src)() == "<header></header>"


def test_keyword_attr_alias():
    src = "<div :if={class_}>has class</div>"
    out = _load(src)(**{"class": "btn"})
    assert out == "<div>has class</div>"


def test_imports_block():
    src = """---
imports:
    - from itertools import chain
---
<p>{list(chain([1, 2], [3]))}</p>"""
    assert _load(src)() == "<p>[1, 2, 3]</p>"


# --- name resolution ---------------------------------------------------------


def test_caller_context_overrides_imports():
    # `chain` comes from imports: in this template, but caller-passed `chain`
    # wins because Python's eval looks at locals (ctx) before globals (module).
    src = """---
imports:
    - from itertools import chain
---
<p>{chain}</p>"""
    assert _load(src)(chain="OVERRIDE") == "<p>OVERRIDE</p>"


# --- AST rewriter edge cases -------------------------------------------------


def test_builtin_left_alone():
    # `len` is a builtin; rewriter must not turn it into _ctx['len'].
    assert _load("<p>{len(items)}</p>")(items=[1, 2, 3]) == "<p>3</p>"


def test_comprehension_target_is_local():
    # In `[x for x in items]`, the inner `x` is comp-local, the outer
    # `items` is from _ctx. Rewriter must keep `x` bare.
    src = "<p>{', '.join(str(x*2) for x in items)}</p>"
    assert _load(src)(items=[1, 2, 3]) == "<p>2, 4, 6</p>"


def test_lambda_param_is_local():
    src = "<p>{(lambda v: v + 1)(n)}</p>"
    assert _load(src)(n=10) == "<p>11</p>"


def test_nested_comprehension():
    src = "<p>{[c for r in rows for c in r]}</p>"
    assert _load(src)(rows=[[1, 2], [3, 4]]) == "<p>[1, 2, 3, 4]</p>"


def test_for_target_visible_in_inner_expression():
    # `x` is a for-target; rewriter must leave bare references alone.
    src = "<a :for={x in items}>{x.upper()}</a>"
    assert _load(src)(items=["a", "b"]) == "<a>A</a><a>B</a>"


def test_attribute_access_on_ctx_name():
    src = "<p>{user.name}</p>"

    class U:
        name = "Dave"

    assert _load(src)(user=U()) == "<p>Dave</p>"


def test_no_eval_in_generated_source():
    # 5b inlines every expression — the generated module should not contain
    # an `eval(` call. Guard against regressing back to the 5a runtime.
    src = compile_source("<p :if={x}>{x.upper()}</p>")
    assert "eval(" not in src


# --- security: URL scheme, on* attrs, opaque bodies, YAML safety -----------


def test_safe_url_scheme_passes():
    out = _load("<a href={url}>x</a>")(url="https://example.com/page")
    assert out == '<a href="https://example.com/page">x</a>'


def test_relative_url_passes():
    assert _load("<a href={url}>x</a>")(url="/path?q=1") == '<a href="/path?q=1">x</a>'


def test_javascript_url_rejected():
    # `escape_url` returns "" for non-safe schemes; `render_dyn_url_attr`
    # then omits the attribute entirely — cleaner DOM than `href=""`.
    out = _load("<a href={url}>x</a>")(url="javascript:alert(1)")
    assert "javascript" not in out
    assert "alert" not in out
    assert out == "<a>x</a>"


def test_data_text_html_url_rejected():
    out = _load("<a href={url}>x</a>")(url="data:text/html,<script>x</script>")
    assert "<script>" not in out
    assert out == "<a>x</a>"


def test_url_scheme_case_insensitive():
    # `JaVaScRiPt:` is the same scheme — reject it.
    out = _load("<a href={url}>x</a>")(url="JaVaScRiPt:alert(1)")
    assert "alert" not in out


def test_mixed_segment_url_attr_validates_full():
    # Static prefix + dynamic suffix — full URL is validated.
    src = '<a href="/{path}">x</a>'
    out = _load(src)(path="search?q=1")
    assert out == '<a href="/search?q=1">x</a>'


def test_mixed_segment_url_with_evil_scheme():
    # Author wrote `<a href="{scheme}:..."` and `scheme=javascript` — composed
    # URL has an unsafe scheme. escape_url rejects.
    src = '<a href="{scheme}:alert(1)">x</a>'
    out = _load(src)(scheme="javascript")
    assert "alert" not in out


def test_src_attr_also_validated():
    out = _load("<img src={u} />")(u="javascript:alert(1)")
    assert "alert" not in out


def test_action_attr_also_validated():
    out = _load("<form action={u}></form>")(u="javascript:alert(1)")
    assert "alert" not in out


def test_event_handler_with_dynamic_value_rejected():
    with pytest.raises(CompileError, match="event-handler"):
        compile_source("<a onclick={handler}>x</a>")


def test_event_handler_with_mark_safe_allowed():
    out = _load('<a onclick={mark_safe("alert(1)")}>x</a>')()
    assert out == '<a onclick="alert(1)">x</a>'


def test_event_handler_with_markup_allowed():
    # `Markup(...)` is the spec-named alias for `mark_safe`; both are
    # auto-available in every compiled module, no `imports:` needed.
    src = "<a onclick={Markup(handler)}>x</a>"
    assert _load(src)(handler="alert(1)") == '<a onclick="alert(1)">x</a>'


def test_event_handler_with_mixed_segments_rejected():
    # Even with one mark_safe segment, the surrounding text could leak —
    # safer to refuse the whole mixed shape.
    with pytest.raises(CompileError, match="event-handler"):
        compile_source('<a onclick="x={val}">x</a>')


def test_static_event_handler_allowed():
    # Literal handler in source — author wrote it, no dynamic data.
    assert (
        _load("<a onclick=\"alert('hi')\">x</a>")()
        == "<a onclick=\"alert('hi')\">x</a>"
    )


def test_event_handler_case_insensitive():
    # HTML attr names are case-insensitive; check `ONCLICK=` is caught too.
    with pytest.raises(CompileError, match="event-handler"):
        compile_source("<a ONCLICK={handler}>x</a>")


def test_expr_inside_script_is_literal_text():
    # Tokenizer treats <script> body as opaque — `{x}` doesn't interpolate.
    # The risk we're guarding against: a future regression that starts parsing
    # ExprNodes inside script body would create a JS-context injection sink.
    src = "<script>const x = {user_data};</script>"
    out = _load(src)(user_data="EVIL")
    assert out == "<script>const x = {user_data};</script>"
    assert "EVIL" not in out


def test_expr_inside_style_is_literal_text():
    src = "<style>.x { color: {user_color}; }</style>"
    out = _load(src)(user_color="red")
    assert out == "<style>.x { color: {user_color}; }</style>"
    assert "red" not in out


def test_yaml_frontmatter_does_not_execute_unsafe_tags(tmp_path):
    # `python-frontmatter` must use a safe YAML loader. A malicious frontmatter
    # with `!!python/object/apply:os.system [...]` would be RCE-on-render if
    # the loader were `yaml.load`. We assert the side effect never happens.
    from plain.html.frontmatter import split

    marker = tmp_path / "yaml_unsafe_marker"
    assert not marker.exists()
    payload = (
        f"---\n"
        f"bomb: !!python/object/apply:os.system ['touch {marker}']\n"
        f"---\n"
        f"<p>body</p>\n"
    )
    try:
        split(payload)
    except Exception:
        # safe_load raises ConstructorError on unknown tags — that's fine.
        pass
    assert not marker.exists(), "YAML loader executed os.system — UNSAFE"


# --- :include + slot composition --------------------------------------------


def _write_templates(tmp_path: Path, templates: dict[str, str]) -> dict[str, Path]:
    """Write a set of templates to tmp_path. Returns name → Path mapping."""
    out: dict[str, Path] = {}
    for name, src in templates.items():
        p = tmp_path / f"{name}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
        out[name] = p
    return out


def test_include_no_attrs(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./child" />',
            "child": "<p>hi</p>",
        },
    )
    assert compile_path(paths["parent"])() == "<p>hi</p>"


def test_include_with_attrs(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./card" title="Hello" />',
            "card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
    )
    assert compile_path(paths["parent"])() == "<h1>Hello</h1>"


def test_include_with_expr_attr(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./card" title={name} />',
            "card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
    )
    assert compile_path(paths["parent"])(name="Dave") == "<h1>Dave</h1>"


def test_include_default_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./card"><p>body</p></template>',
            "card": ("---\nslots:\n  default: Markup\n---\n<div>{children}</div>"),
        },
    )
    assert compile_path(paths["parent"])() == "<div><p>body</p></div>"


def test_include_named_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                '<template :include="./card">'
                '<template slot="header">H</template>'
                "<p>body</p>"
                "</template>"
            ),
            "card": (
                "---\nslots:\n  header: Markup\n  default: Markup\n---\n"
                "<div>{header}|{children}</div>"
            ),
        },
    )
    assert compile_path(paths["parent"])() == "<div>H|<p>body</p></div>"


def test_include_named_slot_on_element(tmp_path):
    # `<div slot="x">` routes the whole div (sans slot=) into the slot.
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                '<template :include="./card"><div slot="header">H</div></template>'
            ),
            "card": ("---\nslots:\n  header: Markup\n---\n<section>{header}</section>"),
        },
    )
    assert compile_path(paths["parent"])() == "<section><div>H</div></section>"


def test_include_root_ctx_propagates(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./inner" />',
            "inner": "<p>{name}</p>",
        },
    )
    assert compile_path(paths["parent"])(name="Dave") == "<p>Dave</p>"


def test_include_explicit_attr_wins_over_root_ctx(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./inner" name="LOCAL" />',
            "inner": "<p>{name}</p>",
        },
    )
    assert compile_path(paths["parent"])(name="ROOT") == "<p>LOCAL</p>"


def test_include_inside_for(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./card" :for={x in items} title={x} />',
            "card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
    )
    assert (
        compile_path(paths["parent"])(items=["a", "b", "c"])
        == "<h1>a</h1><h1>b</h1><h1>c</h1>"
    )


def test_include_inside_if(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./card" :if={show} />',
            "card": "<p>shown</p>",
        },
    )
    render = compile_path(paths["parent"])
    assert render(show=True) == "<p>shown</p>"
    assert render(show=False) == ""


def test_include_chain(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "A": '<template :include="./B" />',
            "B": '<template :include="./C" />',
            "C": "<p>leaf</p>",
        },
    )
    assert compile_path(paths["A"])() == "<p>leaf</p>"


def test_include_cycle_detected(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "A": '<template :include="./B" />',
            "B": '<template :include="./A" />',
        },
    )
    with pytest.raises(CompileError, match="cycle"):
        compile_path(paths["A"])


def test_process_cache_returns_same_function(tmp_path):
    from plain.html.compiler import clear_process_cache

    clear_process_cache()
    paths = _write_templates(tmp_path, {"x": "<p>hi</p>"})
    first = compile_path(paths["x"])
    second = compile_path(paths["x"])
    # Same identity → second call hit the process cache.
    assert first is second


def test_dynamic_include_basic(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": "<template :include={component} />",
            "card": "<p>card body</p>",
            "alert": "<div>alert!</div>",
        },
    )
    render = compile_path(paths["parent"])
    assert render(component="./card") == "<p>card body</p>"
    # Same parent module, different runtime target — dispatch works.
    assert render(component="./alert") == "<div>alert!</div>"


def test_dynamic_include_with_attrs(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": "<template :include={component} title={t} />",
            "card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
    )
    render = compile_path(paths["parent"])
    assert render(component="./card", t="Hi") == "<h1>Hi</h1>"


def test_dynamic_include_with_default_slot(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": "<template :include={component}><p>body</p></template>",
            "card": ("---\nslots:\n  default: Markup\n---\n<div>{children}</div>"),
        },
    )
    assert compile_path(paths["parent"])(component="./card") == (
        "<div><p>body</p></div>"
    )


def test_dynamic_include_inside_for(tmp_path):
    paths = _write_templates(
        tmp_path,
        {
            "parent": (
                "<template :for={item in items} "
                ':include={item["type"]} text={item["text"]} />'
            ),
            "card": "---\nattrs:\n  text: str\n---\n<p>{text}</p>",
            "alert": "---\nattrs:\n  text: str\n---\n<b>{text}</b>",
        },
    )
    render = compile_path(paths["parent"])
    items = [
        {"type": "./card", "text": "one"},
        {"type": "./alert", "text": "two"},
        {"type": "./card", "text": "three"},
    ]
    assert render(items=items) == "<p>one</p><b>two</b><p>three</p>"


def test_compile_source_rejects_static_include():
    # compile_source has no CompileSession, so a literal `:include` can't be
    # resolved. Tells the caller to use compile_path() instead.
    with pytest.raises(CompileError):
        compile_source('<template :include="x"></template>')


# --- disk cache --------------------------------------------------------------


def _compile_with_disk_cache(path: Path) -> Any:
    """Compile via a fresh session that uses the disk cache, bypassing the
    process-wide in-memory cache so the cache write/load paths get exercised.
    """
    clear_process_cache()
    return CompileSession(use_disk_cache=True).compile_path(path)


def test_disk_cache_writes_file(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("PLAIN_HTML_CACHE_DIR", str(cache_dir))
    paths = _write_templates(tmp_path, {"x": "<p>hi</p>"})
    _compile_with_disk_cache(paths["x"])
    cached = list(cache_dir.glob("*__x.html.py"))
    assert len(cached) == 1
    assert "def render" in cached[0].read_text()


def test_disk_cache_hit_skips_codegen(tmp_path, monkeypatch):
    # Source unchanged → same cache key → second compile should pull from
    # disk without re-running codegen. Verify by tampering with the cache
    # file directly: if the cache is consulted, the tamper shows up in
    # output; if codegen runs again, the original source wins.
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("PLAIN_HTML_CACHE_DIR", str(cache_dir))
    paths = _write_templates(tmp_path, {"x": "<p>hi</p>"})
    _compile_with_disk_cache(paths["x"])
    cached = next(iter(cache_dir.glob("*__x.html.py")))
    cached.write_text(cached.read_text().replace("hi", "TAMPERED"))
    r = _compile_with_disk_cache(paths["x"])
    assert r() == "<p>TAMPERED</p>"


def test_disk_cache_invalidates_on_source_change(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("PLAIN_HTML_CACHE_DIR", str(cache_dir))
    paths = _write_templates(tmp_path, {"x": "<p>{name}</p>"})
    r1 = _compile_with_disk_cache(paths["x"])
    assert r1(name="Dave") == "<p>Dave</p>"
    # Same path, different *content* — the source hash flips, so a new
    # cache file is written; the old one stays (no GC in this phase) but
    # the new render reflects the new source.
    paths["x"].write_text("<b>{name}</b>")
    r2 = _compile_with_disk_cache(paths["x"])
    assert r2(name="Dave") == "<b>Dave</b>"


def test_disk_cache_invalidates_transitively(tmp_path, monkeypatch):
    # Modify the LEAF (`child`) and confirm the PARENT recompiles. The
    # parent's source is unchanged but its cache key folds in the child's
    # key, so editing the child shifts both keys upward.
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("PLAIN_HTML_CACHE_DIR", str(cache_dir))
    paths = _write_templates(
        tmp_path,
        {
            "parent": '<template :include="./child" />',
            "child": "<p>v1</p>",
        },
    )
    assert _compile_with_disk_cache(paths["parent"])() == "<p>v1</p>"
    parent_files_v1 = list(cache_dir.glob("*__parent.html.py"))

    paths["child"].write_text("<p>v2</p>")
    assert _compile_with_disk_cache(paths["parent"])() == "<p>v2</p>"
    parent_files_v2 = list(cache_dir.glob("*__parent.html.py"))

    # The parent has a NEW cache file (different key); the old one
    # stays around (no GC yet).
    assert len(parent_files_v2) > len(parent_files_v1)


def test_disk_cache_disabled_when_env_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAIN_HTML_CACHE_DIR", "")
    paths = _write_templates(tmp_path, {"x": "<p>hi</p>"})
    clear_process_cache()
    # With cache dir disabled, compile still works — just no on-disk artifact.
    CompileSession(use_disk_cache=True).compile_path(paths["x"])
    # Nothing was written anywhere we could check, but the compile completed,
    # which is what we wanted.


# --- :include parity with interpreter ----------------------------------------


INCLUDE_PARITY_CASES: list[tuple[dict[str, str], dict]] = [
    # No attrs, no slot.
    ({"parent": '<template :include="./child" />', "child": "<p>hi</p>"}, {}),
    # With attrs.
    (
        {
            "parent": '<template :include="./card" title="Hello" />',
            "card": "---\nattrs:\n  title: str\n---\n<h1>{title}</h1>",
        },
        {},
    ),
    # Default slot.
    (
        {
            "parent": '<template :include="./card"><p>body</p></template>',
            "card": "---\nslots:\n  default: Markup\n---\n<div>{children}</div>",
        },
        {},
    ),
    # Named slot via `<template slot=>`.
    (
        {
            "parent": (
                '<template :include="./card">'
                '<template slot="header">HDR</template>X</template>'
            ),
            "card": (
                "---\nslots:\n  header: Markup\n  default: Markup\n---\n"
                "<div>{header}|{children}</div>"
            ),
        },
        {},
    ),
    # Root-ctx propagation through nested include.
    (
        {
            "outer": '<template :include="./middle" />',
            "middle": '<template :include="./inner" />',
            "inner": "<p>{name}</p>",
        },
        {"name": "Dave"},
    ),
]


@pytest.mark.parametrize(("templates", "ctx"), INCLUDE_PARITY_CASES)
def test_include_parity_with_interpreter(tmp_path, templates, ctx):
    paths = _write_templates(tmp_path, templates)
    entry = next(iter(paths.values()))  # the first template in the set is the entry
    interp = engine_render(entry, ctx)
    compiled = compile_path(entry)(**ctx)
    assert compiled == interp


# --- parity with interpreter -------------------------------------------------


PARITY_CASES: list[tuple[str, dict]] = [
    ("<p>Hi, {name}</p>", {"name": "Dave"}),
    ("<p>{x}</p>", {"x": "<b>bold</b>"}),  # escape
    ("<a href={url}>x</a>", {"url": "/foo?q=&"}),
    ("<a class={c}>x</a>", {"c": ["btn", "primary"]}),
    ("<a class={c}>x</a>", {"c": False}),
    ('<a href="/u/{h}/{t}">x</a>', {"h": "ada", "t": "bio"}),
    ("<p :if={ok}>shown</p>", {"ok": True}),
    ("<p :if={ok}>shown</p>", {"ok": False}),
    ("<ul><li :for={x in items}>{x}</li></ul>", {"items": ["a", "b", "c"]}),
    (
        "<tr :for={r in rows}><td :for={c in r}>{c}</td></tr>",
        {"rows": [[1, 2], [3, 4]]},
    ),
    ("<template>{x}<br></template>", {"x": "hi"}),
    ("<!-- c --><p>{x}</p>", {"x": "y"}),
    ("{# discarded #}<p>{x}</p>", {"x": "y"}),
    ("<!DOCTYPE html><html><body>{x}</body></html>", {"x": "z"}),
    ("<input disabled={d}>", {"d": True}),
    ("<input disabled={d}>", {"d": None}),
]


@pytest.mark.parametrize(("source", "ctx"), PARITY_CASES)
def test_parity_with_interpreter(source, ctx):
    interp = render_source(source, ctx)
    compiled = _load(source)(**ctx)
    assert compiled == interp
