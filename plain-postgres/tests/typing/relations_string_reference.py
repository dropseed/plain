"""A string model reference gets the same typed surface as a class reference.

`ForeignKeyField("package.Model")` / `("self")` is a runtime device for the
cases where the related class isn't importable at the point of declaration --
an import cycle, a self-reference, a framework package pointing at the app's
`User`. The string says nothing to the checker, so `T` is solved from the
`Field[...]` annotation instead (bidirectional inference), and the string
overloads return the same `_ForeignKeyDescriptor[T, V]` the class overloads do.

Everything the class-referenced case promises therefore has to hold here too:
class access is `type[Related]`, instance access is the value type, traversal
type-checks, and the constructor is typed. Those promises are stated for the
class case in relations_foreign_key.py; this file re-states them through the
string.

Runtime half: tests/public/test_typed_where_fk.py.
"""

from typing import assert_type

from app.examples.models.delete import CircA, CircB
from app.examples.models.trees import TreeNode
from plain.postgres import Field, types
from plain.postgres.base import Model
from plain.postgres.query_utils import Q

from plain import postgres


class StringRefTarget(Model):
    """Stands in for a model another package can't import at runtime."""

    model_options = postgres.Options(package_label="examples")

    email: Field[str] = types.TextField(max_length=100)


class StringRefSource(Model):
    """The cross-package shape: a required FK named by string, annotated
    `Field[...]` with the target imported for typing only."""

    model_options = postgres.Options(package_label="examples")

    owner: Field[StringRefTarget] = types.ForeignKeyField(
        "examples.StringRefTarget", on_delete=postgres.CASCADE
    )


def must_accept_class_access_as_the_related_model() -> None:
    assert_type(StringRefSource.owner, type[StringRefTarget])
    # `"CircB"` is a forward reference to a model declared further down the
    # module; `"self"` is the self-reference. Both nullable, both traversable.
    assert_type(CircA.partner, type[CircB])
    assert_type(TreeNode.parent, type[TreeNode])


def must_accept_instance_access_as_the_value_type(
    source: StringRefSource, node: TreeNode
) -> None:
    assert_type(source.owner, StringRefTarget)
    # Nullable string-ref FK: `Field[TreeNode | None]` -> `TreeNode | None`.
    assert_type(node.parent, TreeNode | None)


def must_accept_traversal_to_a_related_field() -> None:
    assert_type(StringRefSource.owner.email.equals("a@b.com"), Q)
    assert_type(StringRefSource.owner.email.startswith("a"), Q)
    # The relation itself is matched through the key it points at.
    assert_type(StringRefSource.owner.id.equals(1), Q)
    assert_type(StringRefSource.owner.id.is_in([1, 2]), Q)
    # Self-reference, and a nullable relation's `is_null`.
    assert_type(TreeNode.parent.name.equals("root"), Q)
    assert_type(TreeNode.parent.id.is_null(), Q)


def must_accept_typed_construction_through_the_string_reference(
    target: StringRefTarget, node: TreeNode
) -> None:
    StringRefSource(owner=target)
    # Nullable + `default=None`: omittable, and None is a value.
    TreeNode(name="root")
    TreeNode(name="leaf", parent=node)
    TreeNode(name="leaf", parent=None)


def must_reject_the_wrong_model_for_a_string_referenced_foreign_key(
    node: TreeNode,
) -> None:
    StringRefSource(owner=node)  # ty: ignore[invalid-argument-type]


def must_reject_a_condition_on_the_relation_itself() -> None:
    # Same as the class-referenced case: `owner.id.equals(...)` is the spelling.
    StringRefSource.owner.equals(1)  # ty: ignore[unresolved-attribute]


class ValueAnnotatedSource(Model):
    """The spelling this change breaks, kept here so the break stays pinned.

    Annotating the attribute with the related model names a model *instance*
    rather than a field, so the checker records no descriptor at all.
    """

    model_options = postgres.Options(package_label="examples")

    # Nullable: the declaration passes `default=`, which is the one case PEP 681
    # compares a field specifier's result against the annotation, so ty rejects
    # it outright.
    backup: StringRefTarget | None = types.ForeignKeyField(  # ty: ignore[invalid-assignment]
        "examples.StringRefTarget",
        on_delete=postgres.SET_NULL,
        allow_null=True,
        required=False,
        default=None,
    )
    # Non-nullable: no `default=`, so the checker never compares the two and
    # this assignment stays silent -- it just quietly costs the whole field
    # surface, as the claims below show. `plain preflight` reports it as
    # `postgres.foreign_key_annotated_as_value`, which is why that check exists.
    owner: StringRefTarget = types.ForeignKeyField(
        "examples.StringRefTarget", on_delete=postgres.CASCADE
    )


def must_reject_traversal_through_a_value_annotated_foreign_key() -> None:
    # `ValueAnnotatedSource.owner` is a `StringRefTarget`, not `type[...]`, so
    # the related field is an instance-level value with no conditions on it.
    ValueAnnotatedSource.owner.email.equals("a@b.com")  # ty: ignore[unresolved-attribute]


def must_reject_a_key_condition_through_a_value_annotated_foreign_key() -> None:
    # `.id` resolves -- as a plain `int`, which has no `equals`.
    ValueAnnotatedSource.owner.id.equals(1)  # ty: ignore[unresolved-attribute]
