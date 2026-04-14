from app.examples.models.iteration import IterationExample


def test_raw_query(db):
    """Test that raw SQL queries work correctly."""
    IterationExample.query.create(name="Toyota", tag="Camry")
    IterationExample.query.create(name="Honda", tag="Civic")
    IterationExample.query.create(name="Ford", tag="F-150")

    rows = list(
        IterationExample.query.raw(
            "SELECT * FROM examples_iterationexample ORDER BY name"
        )
    )
    assert len(rows) == 3
    assert all(isinstance(r, IterationExample) for r in rows)

    names = [r.name for r in rows]  # ty: ignore[unresolved-attribute]
    assert names == ["Ford", "Honda", "Toyota"]


def test_raw_query_with_params(db):
    """Test raw queries with parameters."""
    IterationExample.query.create(name="Toyota", tag="Camry")
    IterationExample.query.create(name="Toyota", tag="Corolla")
    IterationExample.query.create(name="Honda", tag="Civic")

    # Tuple params
    rows = list(
        IterationExample.query.raw(
            "SELECT * FROM examples_iterationexample WHERE name = %s", ("Toyota",)
        )
    )
    assert len(rows) == 2
    assert all(r.name == "Toyota" for r in rows)  # ty: ignore[unresolved-attribute]

    # List params (user-friendly — converted to tuple internally)
    rows = list(
        IterationExample.query.raw(
            "SELECT * FROM examples_iterationexample WHERE name = %s", ["Honda"]
        )
    )
    assert len(rows) == 1
    assert rows[0].name == "Honda"  # ty: ignore[unresolved-attribute]
