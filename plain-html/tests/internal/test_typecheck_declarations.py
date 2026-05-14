from __future__ import annotations

import pytest

from plain.html.typecheck.declarations import (
    DeclarationError,
    parse,
)


def test_inline_attrs_split_type_and_default():
    decls = parse(
        {
            "attrs": {
                "name": "str",
                "count": "int = 0",
                "show": "bool = False",
                "items": "list[int] = [1, 2, 3]",
            },
        }
    )
    by_name = {a.name: a for a in decls.attrs}
    assert by_name["name"].type_source == "str"
    assert by_name["name"].default_source is None
    assert by_name["name"].required is True

    assert by_name["count"].type_source == "int"
    assert by_name["count"].default_source == "0"
    assert by_name["count"].required is False

    assert by_name["items"].type_source == "list[int]"
    assert by_name["items"].default_source == "[1, 2, 3]"


def test_expanded_attr_form():
    decls = parse(
        {
            "attrs": {
                "field": {
                    "type": "plain.forms.fields.FormField",
                    "required": True,
                    "doc": "Form field.",
                },
                "variant": {
                    "type": 'Literal["primary", "danger"]',
                    "default": "primary",
                },
            },
        }
    )
    by_name = {a.name: a for a in decls.attrs}
    assert by_name["field"].type_source == "plain.forms.fields.FormField"
    assert by_name["field"].required is True
    assert by_name["field"].doc == "Form field."

    assert by_name["variant"].type_source == "Literal['primary', 'danger']"
    assert by_name["variant"].default_source == "'primary'"


def test_imports_are_validated():
    decls = parse(
        {
            "imports": [
                "from datetime import datetime",
                "import json",
            ],
        }
    )
    assert [i.statement for i in decls.imports] == [
        "from datetime import datetime",
        "import json",
    ]


def test_imports_rejects_non_imports():
    with pytest.raises(DeclarationError):
        parse({"imports": ["x = 1"]})


def test_slots_inline_form():
    decls = parse(
        {
            "slots": {
                "default": "required",
                "header": "optional",
            },
        }
    )
    by_name = {s.name: s for s in decls.slots}
    assert by_name["default"].required is True
    assert by_name["header"].required is False
    assert by_name["default"].yields_source is None


def test_slots_expanded_form_with_yields():
    decls = parse(
        {
            "slots": {
                "col": {
                    "required": True,
                    "yields": "app.users.User",
                },
            },
        }
    )
    slot = decls.slots[0]
    assert slot.name == "col"
    assert slot.required is True
    assert slot.yields_source == "app.users.User"


def test_attrs_rejects_invalid_identifier():
    with pytest.raises(DeclarationError):
        parse({"attrs": {"bad-name": "str"}})


def test_attrs_rejects_invalid_type_expr():
    with pytest.raises(DeclarationError):
        parse({"attrs": {"x": "str = "}})
