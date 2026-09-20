"""bulk_upsert() locks rows in conflict-key order, whatever shape they are.

Two callers touching overlapping keys deadlock unless they take the locks in
the same order. The order is the sorted conflict key -- and it has to span
every object, not each statement, because a caller whose objects carry ids
sends them in a separate statement from one whose objects don't. Sorting
within each statement would let two callers holding the same four keys lock
them as (a,b),(c,d) and (c,d),(a,b).

This pins the emitted order rather than racing two sessions: the order is the
whole guarantee, and asserting it directly can't flake.
"""

from __future__ import annotations

from app.examples.models.upsert import UpsertItem
from plain.postgres.query import QuerySet


def sent_key_runs(monkeypatch, items) -> list[list[str]]:
    """The keys bulk_upsert() sends, grouped by statement."""
    runs: list[list[str]] = []
    original = QuerySet._batched_insert

    def recording(self, objs, fields, batch_size, **kwargs):
        runs.append([obj.key for obj in objs])
        return original(self, objs, fields, batch_size, **kwargs)

    monkeypatch.setattr(QuerySet, "_batched_insert", recording)
    UpsertItem.query.bulk_upsert(
        items, update_fields=[UpsertItem.value], unique_fields=[UpsertItem.key]
    )
    return runs


def test_lock_order_is_the_sorted_key_when_no_object_carries_an_id(db, monkeypatch):
    items = [UpsertItem(key=key, value=1) for key in ("d", "b", "c", "a")]
    runs = sent_key_runs(monkeypatch, items)

    assert runs == [["a", "b", "c", "d"]]


def test_lock_order_is_the_same_when_some_objects_carry_ids(db, monkeypatch):
    # The reviewer's scenario: the same four keys, but c and d arrive with ids,
    # so they need their own statement. The keys still go out in sorted order.
    items = []
    for key in ("d", "b", "c", "a"):
        item = UpsertItem(key=key, value=1)
        if key in ("c", "d"):
            item.id = {"c": 101, "d": 102}[key]
        items.append(item)
    runs = sent_key_runs(monkeypatch, items)

    assert runs == [["a", "b"], ["c", "d"]]
    assert [key for run in runs for key in run] == ["a", "b", "c", "d"]


def test_ids_interleaved_through_the_key_order_cost_a_statement_each(db, monkeypatch):
    # A new statement starts only where the shape changes, so alternating ids
    # is the worst case -- and the key order still holds across all of them.
    items = []
    for index, key in enumerate(("a", "b", "c", "d")):
        item = UpsertItem(key=key, value=1)
        if index % 2 == 0:
            item.id = 100 + index
        items.append(item)
    runs = sent_key_runs(monkeypatch, items)

    assert runs == [["a"], ["b"], ["c"], ["d"]]


def test_batch_size_splits_within_a_run_without_disturbing_the_order(db, monkeypatch):
    items = [UpsertItem(key=key, value=1) for key in ("d", "b", "c", "a")]
    runs: list[list[str]] = []
    original = QuerySet._batched_insert

    def recording(self, objs, fields, batch_size, **kwargs):
        runs.append([obj.key for obj in objs])
        return original(self, objs, fields, batch_size, **kwargs)

    monkeypatch.setattr(QuerySet, "_batched_insert", recording)
    UpsertItem.query.bulk_upsert(
        items,
        update_fields=[UpsertItem.value],
        unique_fields=[UpsertItem.key],
        batch_size=2,
    )

    # batch_size caps the statement inside a run; the run is still one call.
    assert runs == [["a", "b", "c", "d"]]
