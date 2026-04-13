"""
Test fixtures for delete / on_delete behavior.

Kept in one place so the main models module isn't cluttered with a dozen
parent/child variants. Imported with `from .delete import *` in the package
__init__ so `@postgres.register_model` fires at import time.
"""

from __future__ import annotations

from plain import postgres
from plain.postgres import types

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
class ChildProtect(postgres.Model):
    parent: DeleteParent = types.ForeignKeyField(
        DeleteParent, on_delete=postgres.PROTECT
    )

    query: postgres.QuerySet[ChildProtect] = postgres.QuerySet()


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
        DeleteParent, on_delete=postgres.CASCADE, db_constraint=False
    )

    query: postgres.QuerySet[UnconstrainedChild] = postgres.QuerySet()


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
# SET(callable) — reassign to a sentinel row
# ---------------------------------------------------------------------------


@postgres.register_model
class SetSentinelParent(postgres.Model):
    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[SetSentinelParent] = postgres.QuerySet()


def _sentinel_parent():
    return SetSentinelParent.query.get(name="sentinel")


@postgres.register_model
class ChildSetCallable(postgres.Model):
    parent: SetSentinelParent = types.ForeignKeyField(
        SetSentinelParent,
        on_delete=postgres.SET(_sentinel_parent),
    )
    parent_id: int

    query: postgres.QuerySet[ChildSetCallable] = postgres.QuerySet()


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
