"""Fixture: every template and fragment here is a literal at its call site."""

from app.examples.models.relationships import Widget
from plain.postgres import Fragment
from plain.postgres import Fragment as ShortFragment

from plain import postgres

# A shared predicate is a Fragment, checked here where its text is written.
ACTIVE = Fragment("size = 'small'")
ALIASED = ShortFragment("size = 'large'")
QUALIFIED = postgres.Fragment("size = 'medium'")


def listing():
    return Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {predicate}", predicate=ACTIVE
    )


def inline(size):
    return Widget.query.sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size=size
    )


def by_keyword(size):
    return Widget.query.sql(
        template="SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}",
        size=size,
    )


def through_a_chain(size):
    return Widget.query.all().sql(
        "SELECT {Widget.*} FROM {Widget} WHERE {Widget.size} = {size}", size=size
    )


def not_our_sql(parsed, dialect):
    """An unrelated object with a `sql()` method is not a written query."""
    return parsed.sql(dialect)
