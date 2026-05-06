from __future__ import annotations

import pytest
from app.examples.models.iteration import IterationExample


@pytest.fixture
def rows(db):
    """Create a set of rows for testing iterator behavior."""
    created = []
    for i in range(50):
        created.append(
            IterationExample.query.create(name=f"Name{i:03d}", tag=f"Tag{i:03d}")
        )
    return created


def test_basic_iteration(rows):
    """iterator() returns all rows."""
    results = list(IterationExample.query.iterator())
    assert len(results) == 50
    assert all(isinstance(r, IterationExample) for r in results)


def test_chunk_size_1(rows):
    """iterator(chunk_size=1) yields correct results."""
    results = list(IterationExample.query.iterator(chunk_size=1))
    assert len(results) == 50


def test_chunk_size_2(rows):
    """iterator(chunk_size=2) yields correct results."""
    results = list(IterationExample.query.iterator(chunk_size=2))
    assert len(results) == 50


def test_filtered_iteration(rows):
    """.filter().iterator() works."""
    results = list(IterationExample.query.filter(name="Name000").iterator())
    assert len(results) == 1
    assert results[0].name == "Name000"


def test_values_iteration(rows):
    """.values().iterator() works through stream path."""
    results = list(IterationExample.query.values("name", "tag").iterator())
    assert len(results) == 50
    assert all(isinstance(r, dict) for r in results)
    assert "name" in results[0]
    assert "tag" in results[0]


def test_values_list_iteration(rows):
    """.values_list().iterator() works through stream path."""
    results = list(IterationExample.query.values_list("name", flat=True).iterator())
    assert len(results) == 50
    assert all(isinstance(r, str) for r in results)


def test_empty_queryset_iteration(db):
    """.none().iterator() yields nothing."""
    results = list(IterationExample.query.none().iterator())
    assert results == []


def test_count_matches_iterator(rows):
    """Iterator yields same count as .count()."""
    count = IterationExample.query.count()
    iter_count = sum(1 for _ in IterationExample.query.iterator())
    assert count == iter_count == 50


def test_ordering_preserved(rows):
    """.order_by().iterator() maintains order."""
    results = list(IterationExample.query.order_by("name").iterator())
    names = [r.name for r in results]
    assert names == sorted(names)

    results_desc = list(IterationExample.query.order_by("-name").iterator())
    names_desc = [r.name for r in results_desc]
    assert names_desc == sorted(names_desc, reverse=True)


def test_large_dataset_small_chunks(rows):
    """50 rows with chunk_size=10 returns all results."""
    results = list(IterationExample.query.order_by("id").iterator(chunk_size=10))
    assert len(results) == 50
    # Verify all unique
    ids = [r.id for r in results]
    assert len(set(ids)) == 50


def test_partial_consumption(rows):
    """Partially consuming an iterator doesn't leak or error."""
    it = IterationExample.query.iterator(chunk_size=2)
    first = next(it)
    assert isinstance(first, IterationExample)
    # Abandon the iterator — should clean up without error
    del it
    # Verify the connection is still usable
    assert IterationExample.query.count() == 50
