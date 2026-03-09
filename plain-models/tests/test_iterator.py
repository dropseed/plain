from __future__ import annotations

import pytest
from app.examples.models import Car


@pytest.fixture
def cars(db):
    """Create a set of cars for testing iterator behavior."""
    created = []
    for i in range(50):
        created.append(Car.query.create(make=f"Make{i:03d}", model=f"Model{i:03d}"))
    return created


def test_basic_iteration(cars):
    """iterator() returns all rows."""
    results = list(Car.query.iterator())
    assert len(results) == 50
    assert all(isinstance(c, Car) for c in results)


def test_chunk_size_1(cars):
    """iterator(chunk_size=1) yields correct results."""
    results = list(Car.query.iterator(chunk_size=1))
    assert len(results) == 50


def test_chunk_size_2(cars):
    """iterator(chunk_size=2) yields correct results."""
    results = list(Car.query.iterator(chunk_size=2))
    assert len(results) == 50


def test_filtered_iteration(cars):
    """.filter().iterator() works."""
    results = list(Car.query.filter(make="Make000").iterator())
    assert len(results) == 1
    assert results[0].make == "Make000"


def test_values_iteration(cars):
    """.values().iterator() works through stream path."""
    results = list(Car.query.values("make", "model").iterator())
    assert len(results) == 50
    assert all(isinstance(r, dict) for r in results)
    assert "make" in results[0]
    assert "model" in results[0]


def test_values_list_iteration(cars):
    """.values_list().iterator() works through stream path."""
    results = list(Car.query.values_list("make", flat=True).iterator())
    assert len(results) == 50
    assert all(isinstance(r, str) for r in results)


def test_empty_queryset_iteration(db):
    """.none().iterator() yields nothing."""
    results = list(Car.query.none().iterator())
    assert results == []


def test_count_matches_iterator(cars):
    """Iterator yields same count as .count()."""
    count = Car.query.count()
    iter_count = sum(1 for _ in Car.query.iterator())
    assert count == iter_count == 50


def test_ordering_preserved(cars):
    """.order_by().iterator() maintains order."""
    results = list(Car.query.order_by("make").iterator())
    makes = [c.make for c in results]
    assert makes == sorted(makes)

    results_desc = list(Car.query.order_by("-make").iterator())
    makes_desc = [c.make for c in results_desc]
    assert makes_desc == sorted(makes_desc, reverse=True)


def test_large_dataset_small_chunks(cars):
    """50 rows with chunk_size=10 returns all results."""
    results = list(Car.query.order_by("id").iterator(chunk_size=10))
    assert len(results) == 50
    # Verify all unique
    ids = [c.id for c in results]
    assert len(set(ids)) == 50


def test_partial_consumption(cars):
    """Partially consuming an iterator doesn't leak or error."""
    it = Car.query.iterator(chunk_size=2)
    first = next(it)
    assert isinstance(first, Car)
    # Abandon the iterator — should clean up without error
    del it
    # Verify the connection is still usable
    assert Car.query.count() == 50
