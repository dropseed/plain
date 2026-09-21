"""Fixture: every template and fragment here is a literal."""

from app.examples.models.relationships import Widget
from plain.postgres import Fragment

ACTIVE = Fragment("size = 'small'")
LISTING = "SELECT {Widget.*} FROM {Widget} WHERE {predicate}"


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
