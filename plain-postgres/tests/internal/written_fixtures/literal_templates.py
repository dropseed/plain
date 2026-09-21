"""Fixture: every template and fragment here is a literal, or a name that can
only ever be one."""

from app.examples.models.relationships import Widget
from plain.postgres import Fragment
from plain.postgres import Fragment as ShortFragment

from plain import postgres

ACTIVE = Fragment("size = 'small'")
ALIASED = ShortFragment("size = 'large'")
QUALIFIED = postgres.Fragment("size = 'medium'")
LISTING: str = "SELECT {Widget.*} FROM {Widget} WHERE {predicate}"


def listing():
    return Widget.query.sql(LISTING, predicate=ACTIVE)


def inline(size):
    return Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size=size
    )


def by_keyword(size):
    return Widget.query.sql(
        template="SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}",
        size=size,
    )


def through_a_custom_queryset(size):
    return Widget.query.all().sql(LISTING, predicate=ACTIVE)


def not_our_sql(parsed, dialect):
    """An unrelated object with a `sql()` method is not a written query."""
    return parsed.sql(dialect)
