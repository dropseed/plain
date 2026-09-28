"""`types.pyi` versus the runtime it describes.

A type checker believes the stub. A stub that promises a keyword argument the
runtime constructor does not take, or declares a method under `TYPE_CHECKING`
with nothing behind it, type-checks perfectly and then raises -- and the
typing corpus in `tests/typing/` cannot catch it either, because the corpus is
checked by the same checker reading the same stub.

So this parses the stub with `ast` and compares it against the live objects.
Both failure modes below have actually happened:

- `only_empty_default` overloads promised `default=` combinations
  `DefaultableField.__init__` rejects;
- `GenericIPAddressField` type-checked `.contains(...)` (the `self` restriction
  admits any string-valued field) and raised at runtime, because it registers
  no `contains` lookup.
"""

import annotationlib
import ast
import inspect
from pathlib import Path
from typing import Any

import pytest
from plain.postgres import types
from plain.postgres.base import ModelBase, ModelMixin
from plain.postgres.fields.base import (
    CONDITION_METHODS,
    STRING_CONDITION_LOOKUPS,
    STRING_CONDITION_METHODS,
    Field,
)
from plain.postgres.fields.encrypted import EncryptedField

# PEP 681 field specifiers take these names from the *checker*, not from the
# runtime -- they configure the synthesized constructor. `init=False` on
# `PrimaryKeyField` is the whole reason `Model(id=...)` is rejected, and no
# runtime signature has it.
PEP_681_PSEUDO_PARAMS = frozenset(
    {"init", "default", "default_factory", "factory", "kw_only", "alias", "converter"}
)

_POSTGRES_PACKAGE = Path(types.__file__).parent


def _parse(relative_path: str) -> ast.Module:
    path = _POSTGRES_PACKAGE / relative_path
    return ast.parse(path.read_text(), filename=str(path))


STUB = _parse("types.pyi")


def _stub_constructors() -> dict[str, list[ast.FunctionDef]]:
    """Every module-level `def` in the stub, keyed by name.

    Overloads repeat the name, so each entry is the list of declarations --
    which is exactly the union we need to compare against the runtime.
    """
    constructors: dict[str, list[ast.FunctionDef]] = {}
    for node in STUB.body:
        if isinstance(node, ast.FunctionDef):
            constructors.setdefault(node.name, []).append(node)
    return constructors


STUB_CONSTRUCTORS = _stub_constructors()

SPECIFIERS = {
    # __dataclass_transform__ is the PEP 681 runtime dunder the decorator
    # sets; ty doesn't model it statically.
    f.__name__: f
    for f in ModelBase.__dataclass_transform__["field_specifiers"]  # ty: ignore[unresolved-attribute]
}


def _declared_parameters(declarations: list[ast.FunctionDef]) -> set[str]:
    names: set[str] = set()
    for node in declarations:
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            names.add(arg.arg)
    return names


# ---------------------------------------------------------------------------
# (1) The stub may not be wider than the runtime constructor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SPECIFIERS))
def test_stub_keyword_arguments_exist_on_the_runtime_constructor(name: str) -> None:
    declared = _declared_parameters(STUB_CONSTRUCTORS[name]) - PEP_681_PSEUDO_PARAMS
    runtime = set(
        inspect.signature(
            SPECIFIERS[name], annotation_format=annotationlib.Format.FORWARDREF
        ).parameters
    )

    extras = sorted(declared - runtime)
    assert not extras, (
        f"types.pyi declares {extras} on {name}(), which "
        f"{SPECIFIERS[name].__module__}.{name}.__init__ does not accept. "
        f"A call using one type-checks and then raises TypeError.\n"
        f"  runtime parameters: {sorted(runtime)}"
    )


# ---------------------------------------------------------------------------
# (2) A type-only declaration must have something behind it.
# ---------------------------------------------------------------------------


def _self_restricted_conditions(module: ast.Module, class_name: str) -> dict[str, str]:
    """Condition methods on `class_name` whose `self` carries an annotation.

    The annotation is the restriction -- `self: Field[str] | Field[str | None]`
    is what keeps `.startswith(...)` off an integer field -- so it is the thing
    that has to stay in step with the runtime. Scoped to `CONDITION_METHODS`
    because `__get__`'s overloads annotate `self` for unrelated reasons.
    """
    restricted: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if not isinstance(child, ast.FunctionDef):
                continue
            if child.name not in CONDITION_METHODS or not child.args.args:
                continue
            first = child.args.args[0]
            if first.arg == "self" and first.annotation is not None:
                restricted[child.name] = ast.unparse(first.annotation)
    return restricted


def _type_checking_declarations(module: ast.Module, class_name: str) -> set[str]:
    """Method names declared inside `if TYPE_CHECKING:` on `class_name`."""
    declared: set[str] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if not isinstance(child, ast.If):
                continue
            if ast.unparse(child.test) != "TYPE_CHECKING":
                continue
            for stmt in child.body:
                if isinstance(stmt, ast.FunctionDef):
                    declared.add(stmt.name)
    return declared


def test_string_conditions_are_the_self_restricted_ones() -> None:
    """`STRING_CONDITION_METHODS` is what the rest of the codebase reads to
    know which conditions are string-only. If a method gains or loses the
    `self` restriction without the tuple moving with it, everything that
    imports the tuple is quietly wrong."""
    restricted = _self_restricted_conditions(_parse("fields/base.py"), "Field")

    assert set(restricted) == set(STRING_CONDITION_METHODS)
    for name, annotation in restricted.items():
        assert annotation == "Field[str] | Field[str | None]", (
            f"Field.{name} restricts `self` to {annotation!r}; the string-valued "
            f"field classes checked below are derived from the str parameterization."
        )


def test_every_type_checking_declaration_names_a_real_condition() -> None:
    """`EncryptedField` re-declares the blocked conditions under
    `TYPE_CHECKING` with `Never` parameters. A name there that isn't a real
    condition blocks nothing, and a condition method added to `Field` later
    that isn't blocked here silently becomes callable on ciphertext."""
    declared = _type_checking_declarations(
        _parse("fields/encrypted.py"), "EncryptedField"
    )

    unknown = sorted(declared - set(CONDITION_METHODS))
    assert not unknown, (
        f"EncryptedField declares {unknown} under TYPE_CHECKING, which are not "
        f"condition methods on Field -- the declaration blocks nothing."
    )
    # `is_null` is the one condition that deliberately stays open.
    missing = sorted(set(CONDITION_METHODS) - declared - {"is_null"})
    assert not missing, (
        f"EncryptedField does not block {missing}. `_build_q` still refuses at "
        f"runtime, but the call site type-checks."
    )
    for name in sorted(declared):
        assert callable(getattr(EncryptedField, name, None)), (
            f"EncryptedField.{name} is declared under TYPE_CHECKING with no "
            f"runtime attribute behind it."
        )


def _stub_value_types(name: str) -> set[str]:
    """The `T`s a constructor's overloads return, e.g. {'str', 'str | None'}."""
    value_types: set[str] = set()
    for node in STUB_CONSTRUCTORS[name]:
        returns = node.returns
        if isinstance(returns, ast.Subscript):
            value_types.add(ast.unparse(returns.slice))
    return value_types


STRING_VALUED_FIELDS = sorted(
    name for name in SPECIFIERS if _stub_value_types(name) & {"str", "str | None"}
)


def test_the_string_valued_field_set_is_not_empty() -> None:
    """Guard the derivation itself: if the stub's return annotations change
    shape, the sweep below would pass by checking nothing."""
    assert "GenericIPAddressField" in STRING_VALUED_FIELDS
    assert "RandomStringField" in STRING_VALUED_FIELDS
    assert "IntegerField" not in STRING_VALUED_FIELDS


@pytest.mark.parametrize("name", STRING_VALUED_FIELDS)
@pytest.mark.parametrize("method", STRING_CONDITION_METHODS)
def test_string_valued_fields_support_the_string_conditions(
    name: str, method: str
) -> None:
    """The `self: Field[str] | Field[str | None]` restriction admits every
    field the stub types as string-valued -- including the ones that don't
    inherit TextField. Each of them has to register the lookup, or the call
    type-checks and raises.

    The exception is a field that blocks the condition statically too: an
    encrypted column has no meaningful substring match, and the `Never`
    declaration is what refuses the call site.
    """
    field_class: Any = SPECIFIERS[name]
    if issubclass(field_class, EncryptedField):
        pytest.skip(f"{name} blocks .{method}() statically (Never) and at runtime")

    lookup = STRING_CONDITION_LOOKUPS[method]
    assert lookup in field_class.get_lookups(), (
        f"{name} is typed `str` by types.pyi, so `Field.{method}`'s `self` "
        f"restriction admits it, but it registers no {lookup!r} lookup -- the "
        f"call type-checks and then raises TypeError from `_build_q`."
    )


def test_condition_methods_all_exist_on_field() -> None:
    for method in CONDITION_METHODS:
        assert callable(getattr(Field, method, None))


# ---------------------------------------------------------------------------
# (3) One field specifier list, spelled in four places.
# ---------------------------------------------------------------------------


def test_field_specifiers_match_the_stub_and_the_mixin() -> None:
    """PEP 681 requires a tuple literal in `@dataclass_transform`, so the
    specifier list is repeated on `ModelBase` and `ModelMixin` rather than
    shared. It also has to match what `types` exports and what the stub
    actually types -- a constructor missing from any of them silently stops
    being treated as a field specifier, and the checker reads its `default=`
    as a plain default value with no error anywhere.
    """
    specifiers = set(SPECIFIERS)
    mixin_specifiers = {
        f.__name__
        for f in ModelMixin.__dataclass_transform__["field_specifiers"]  # ty: ignore[unresolved-attribute]
    }
    stub_constructors = set(STUB_CONSTRUCTORS)
    exported = {name for name in types.__all__ if name.endswith("Field")}

    assert specifiers == mixin_specifiers, (
        "ModelMixin's @dataclass_transform has drifted from ModelBase's:\n"
        f"  only on ModelBase: {sorted(specifiers - mixin_specifiers)}\n"
        f"  only on ModelMixin: {sorted(mixin_specifiers - specifiers)}"
    )
    assert specifiers == stub_constructors, (
        "field_specifiers and types.pyi disagree about which constructors exist:\n"
        f"  no stub declaration: {sorted(specifiers - stub_constructors)}\n"
        f"  not a field specifier: {sorted(stub_constructors - specifiers)}"
    )
    # The non-`*Field` exports are reverse-relation accessors / managers, which
    # are never constructor fields (they're declared `ClassVar`).
    assert specifiers == exported, (
        "field_specifiers is out of sync with what plain.postgres.types exports:\n"
        f"  missing from field_specifiers: {sorted(exported - specifiers)}\n"
        f"  stale in field_specifiers: {sorted(specifiers - exported)}"
    )
