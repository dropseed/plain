"""Test fixtures for delete / on_delete behavior."""

from __future__ import annotations

from typing import ClassVar

from plain import postgres
from plain.postgres import Field, types
from plain.postgres.query_utils import Q

# ---------------------------------------------------------------------------
# Single-level: one parent, one child per on_delete option
# ---------------------------------------------------------------------------


@postgres.register_model
class DeleteParent(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)

    childcascade_set: types.ReverseForeignKey[ChildCascade] = types.ReverseForeignKey(
        to="ChildCascade", field="parent"
    )


@postgres.register_model
class ChildCascade(postgres.Model):
    parent: Field[DeleteParent] = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.CASCADE
    )


@postgres.register_model
class ChildRestrict(postgres.Model):
    parent: Field[DeleteParent] = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.RESTRICT
    )


@postgres.register_model
class ChildSetNull(postgres.Model):
    parent: Field[DeleteParent | None] = types.ForeignKeyField(
        DeleteParent,
        on_delete=postgres.SET_NULL,
        allow_null=True,
        default=None,
    )


@postgres.register_model
class ChildNoAction(postgres.Model):
    parent: Field[DeleteParent] = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.NO_ACTION
    )


@postgres.register_model
class UnconstrainedChild(postgres.Model):
    """FK with db_constraint=False — no DB constraint, convergence should ignore."""

    parent: Field[DeleteParent] = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.NO_ACTION, db_constraint=False
    )


class _HideGhostsQuerySet(postgres.QuerySet):
    """QuerySet with a default filter. Rows named "ghost" are hidden from
    the public queryset — mirrors real-world patterns like soft-delete or
    tenant scoping. Used to verify Model.delete() bypasses custom filters.

    Filter is applied to the underlying SQL query directly to avoid the
    recursion that would happen if we called .exclude() (which clones via
    from_model)."""

    @classmethod
    def from_model(cls, model, query=None):
        instance = super().from_model(model, query)
        instance._query.add_q(~Q(name="ghost"))
        return instance


@postgres.register_model
class HideableItem(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)

    query: ClassVar[_HideGhostsQuerySet] = _HideGhostsQuerySet()


# ---------------------------------------------------------------------------
# Multi-level: Grandparent → MidParent → Grandchild
# ---------------------------------------------------------------------------


@postgres.register_model
class Grandparent(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)


@postgres.register_model
class MidParent(postgres.Model):
    grandparent: Field[Grandparent] = types.ForeignKeyField(
        Grandparent, on_delete=postgres.CASCADE
    )


@postgres.register_model
class Grandchild(postgres.Model):
    mid_parent: Field[MidParent] = types.ForeignKeyField(
        MidParent, on_delete=postgres.CASCADE
    )


# ---------------------------------------------------------------------------
# Diamond: two parents cascading into a shared child
# ---------------------------------------------------------------------------


@postgres.register_model
class DiamondParentA(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)


@postgres.register_model
class DiamondParentB(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)


@postgres.register_model
class DiamondChild(postgres.Model):
    parent_a: Field[DiamondParentA] = types.ForeignKeyField(
        DiamondParentA, on_delete=postgres.CASCADE
    )
    parent_b: Field[DiamondParentB] = types.ForeignKeyField(
        DiamondParentB, on_delete=postgres.CASCADE
    )


# ---------------------------------------------------------------------------
# Circular FKs — A.partner → B, B.partner → A, both CASCADE. Relies on
# DEFERRABLE INITIALLY DEFERRED for circular insertion and deletion.
# ---------------------------------------------------------------------------


@postgres.register_model
class CircA(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    partner: CircB | None = types.ForeignKeyField(
        "CircB",
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
    )


@postgres.register_model
class CircB(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    partner: Field[CircA | None] = types.ForeignKeyField(
        CircA,
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
        default=None,
    )
