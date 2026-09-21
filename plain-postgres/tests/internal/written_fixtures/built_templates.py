"""Fixture: every template and fragment here is built at runtime."""

from app.examples.models.relationships import Widget
from plain.postgres import Fragment, Written
from plain.postgres import Fragment as ShortFragment

REBOUND = "SELECT {Widget.*} FROM {Widget}"
REBOUND = REBOUND + " ORDER BY 1"

LOOPED = "SELECT 1"
for LOOPED in ("SELECT 2", "SELECT 3"):
    pass


def f_string(size):
    return Widget.query.sql(f"SELECT {{Widget.*}} FROM {{Widget}} WHERE s = '{size}'")


def concatenated(order):
    return Widget.query.sql("SELECT {Widget.*} FROM {Widget} ORDER BY " + order)


def from_a_call(builder):
    return Widget.query.sql(builder())


def from_a_variable(template):
    return Widget.query.sql(template)


def keyword_template(template):
    return Widget.query.sql(template=template)


def from_a_rebound_module_name():
    return Widget.query.sql(REBOUND)


def from_a_loop_variable():
    return Widget.query.sql(LOOPED)


def fragment_from_a_variable(text):
    return Fragment(text)


def fragment_by_keyword(text):
    return Fragment(text=text)


def fragment_from_an_or(text):
    return Fragment(text or "")


def fragment_through_an_alias(text):
    return ShortFragment(text)


def written_directly(template):
    return Written(model=Widget, template=template, values={})
