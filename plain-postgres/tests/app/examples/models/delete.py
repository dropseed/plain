"""
Test fixtures for delete / on_delete behavior.

Kept in one place so the main models module isn't cluttered with a dozen
parent/child variants. Imported with `from .delete import *` in the package
__init__ so `@postgres.register_model` fires at import time.
"""

from __future__ import annotations

from plain import postgres
from plain.postgres import types
from plain.postgres.query_utils import Q

# ---------------------------------------------------------------------------
# Single-level: one parent, one child per on_delete option
# ---------------------------------------------------------------------------


@postgres.register_model
class DeleteParent(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[DeleteParent] = postgres.QuerySet()

    childcascade_set: types.ReverseForeignKey[ChildCascade] = types.ReverseForeignKey(
        to="ChildCascade", field="parent"
    )


@postgres.register_model
class ChildCascade(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.CASCADE
    )

    query: postgres.QuerySet[ChildCascade] = postgres.QuerySet()


@postgres.register_model
class ChildRestrict(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.RESTRICT
    )

    query: postgres.QuerySet[ChildRestrict] = postgres.QuerySet()


@postgres.register_model
class ChildSetNull(postgres.Model):
    parent: DeleteParent | None = types.ForeignKeyField(
        DeleteParent,
        on_delete=postgres.SET_NULL,
        allow_null=True,
    )
    parent_id: int | None

    query: postgres.QuerySet[ChildSetNull] = postgres.QuerySet()


@postgres.register_model
class ChildNoAction(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.NO_ACTION
    )

    query: postgres.QuerySet[ChildNoAction] = postgres.QuerySet()


@postgres.register_model
class UnconstrainedChild(postgres.Model):
    """FK with db_constraint=False — no DB constraint, convergence should ignore."""

    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.NO_ACTION, db_constraint=False
    )

    query: postgres.QuerySet[UnconstrainedChild] = postgres.QuerySet()


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
    name: str = types.TextField(max_length=100)

    query = _HideGhostsQuerySet()


# ---------------------------------------------------------------------------
# Multi-level: Grandparent → MidParent → Grandchild
# ---------------------------------------------------------------------------


@postgres.register_model
class Grandparent(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[Grandparent] = postgres.QuerySet()


@postgres.register_model
class MidParent(postgres.Model):
    grandparent: Grandparent = types.ForeignKeyField(
        Grandparent, on_delete=postgres.CASCADE
    )

    query: postgres.QuerySet[MidParent] = postgres.QuerySet()


@postgres.register_model
class Grandchild(postgres.Model):
    mid_parent: MidParent = types.ForeignKeyField(MidParent, on_delete=postgres.CASCADE)

    query: postgres.QuerySet[Grandchild] = postgres.QuerySet()


# ---------------------------------------------------------------------------
# Diamond: two parents cascading into a shared child
# ---------------------------------------------------------------------------


@postgres.register_model
class DiamondParentA(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[DiamondParentA] = postgres.QuerySet()


@postgres.register_model
class DiamondParentB(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[DiamondParentB] = postgres.QuerySet()


@postgres.register_model
class DiamondChild(postgres.Model):
    parent_a: DiamondParentA = types.ForeignKeyField(
        DiamondParentA, on_delete=postgres.CASCADE
    )
    parent_b: DiamondParentB = types.ForeignKeyField(
        DiamondParentB, on_delete=postgres.CASCADE
    )

    query: postgres.QuerySet[DiamondChild] = postgres.QuerySet()


# ---------------------------------------------------------------------------
# Circular FKs — A.partner → B, B.partner → A, both CASCADE. Relies on
# DEFERRABLE INITIALLY DEFERRED for circular insertion and deletion.
# ---------------------------------------------------------------------------


@postgres.register_model
class CircA(postgres.Model):
    name: str = types.TextField(max_length=100)
    partner: CircB | None = types.ForeignKeyField(
        "CircB",
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
    )
    partner_id: int | None

    query: postgres.QuerySet[CircA] = postgres.QuerySet()


@postgres.register_model
class CircB(postgres.Model):
    name: str = types.TextField(max_length=100)
    partner: CircA | None = types.ForeignKeyField(
        CircA,
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
    )
    partner_id: int | None

    query: postgres.QuerySet[CircB] = postgres.QuerySet()
